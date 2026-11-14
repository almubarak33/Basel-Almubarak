"""HTTP ingress and worker loop.

TradingView cancels a webhook that takes longer than three seconds and does not retry it, so the HTTP handler only
authenticates, queues the message and answers 202. One worker thread does all trading work, in order.
"""
import hmac
import json
import logging
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("sabika.bridge")


class BridgeServer:
    def __init__(self, cfg, engine, manage_every=2.0):
        self.cfg, self.engine, self.manage_every = cfg, engine, manage_every
        self.inbox = queue.Queue(maxsize=1000)
        self._stop = threading.Event()
        self.httpd = ThreadingHTTPServer((cfg.host, cfg.port), self._handler())
        self.port = self.httpd.server_address[1]
        self._threads = [threading.Thread(target=self.httpd.serve_forever, name="http", daemon=True),
                         threading.Thread(target=self._work, name="worker", daemon=True)]

    def _authorised(self, path, prefix):
        return path.startswith(prefix) and hmac.compare_digest(path[len(prefix):].encode(), self.cfg.secret.encode())

    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):          # keep the secret-bearing path out of the default access log
                pass

            def _send(self, code, body=b"", ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                if not server._authorised(self.path, "/tv/"):
                    return self._send(404)
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > server.cfg.max_body_bytes:
                    return self._send(413)
                try:
                    msg = json.loads(self.rfile.read(length).decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    return self._send(400)
                try:
                    server.inbox.put_nowait(msg)
                except queue.Full:
                    return self._send(503)
                self._send(202, b'{"ok":true}')

            def do_GET(self):
                if self.path == "/health":
                    return self._send(200, b"ok", "text/plain")
                if server._authorised(self.path, "/status/"):
                    return self._send(200, json.dumps(server.engine.status(), default=str).encode())
                self._send(404)

        return Handler

    def _work(self):
        next_manage = 0.0
        while not self._stop.is_set():
            try:
                msg = self.inbox.get(timeout=0.5)
            except queue.Empty:
                msg = None
            try:
                if msg is not None:
                    d = self.engine.handle(msg)
                    if d["status"] != "heartbeat" or d.get("reason"):
                        log.info("message -> %s %s %s", d["status"], d.get("reason", ""), json.dumps(d.get("detail", {}), default=str))
                if time.monotonic() >= next_manage:
                    self.engine.manage()
                    next_manage = time.monotonic() + self.manage_every
            except Exception:                       # never let one bad message or broker hiccup stop the worker
                log.exception("worker error")
                next_manage = time.monotonic() + self.manage_every

    def start(self):
        for t in self._threads:
            t.start()
        log.info("listening on %s:%d, mode=%s", self.cfg.host, self.port, self.cfg.mode)

    def stop(self):
        self._stop.set()
        self.httpd.shutdown()
        self.httpd.server_close()
