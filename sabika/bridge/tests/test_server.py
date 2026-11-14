import json
import time
import unittest
import urllib.error
import urllib.request

from sabika_bridge.broker_sim import SimBroker
from sabika_bridge.config import Config, Risk, Source
from sabika_bridge.engine import Engine
from sabika_bridge.server import BridgeServer
from sabika_bridge.store import Store

SECRET = "s3cret-s3cret-s3cret"


def call(url, body=None):
    req = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class EndToEnd(unittest.TestCase):
    def setUp(self):
        cfg = Config(mode="demo", secret=SECRET, port=0, risk=Risk(), symbols={"CAPITALCOM:XAUUSD": "GOLD"},
                     sources={"GOLDV2": Source(enabled=True)})
        self.broker = SimBroker()
        self.broker.add_symbol("GOLD", 3900.00, 3900.30)
        self.engine = Engine(cfg, self.broker, Store(":memory:"))
        self.server = BridgeServer(cfg, self.engine, manage_every=0.2)
        self.server.start()
        self.base = "http://127.0.0.1:%d" % self.server.port

    def tearDown(self):
        self.server.stop()

    def test_webhook_to_order(self):
        now_ms = int(time.time() * 1000)
        msg = {"v": 1, "type": "entry", "src": "GOLDV2", "sym": "CAPITALCOM:XAUUSD", "tf": 5, "side": "buy",
               "id": "GOLDV2-5-%d" % now_ms, "t": now_ms, "entry": 3900.30, "sl": 3880.30, "tp1": 3920.30,
               "tp2": 3930.30, "tp3": 3940.30, "expire": now_ms + 7200000}
        body = json.dumps(msg).encode()
        self.assertEqual(call(self.base + "/tv/wrong-secret", body)[0], 404)
        self.assertEqual(call(self.base + "/tv/" + SECRET, b"not json")[0], 400)
        started = time.time()
        code, _ = call(self.base + "/tv/" + SECRET, body)
        self.assertEqual(code, 202)
        self.assertLess(time.time() - started, 1.0, "the webhook must be acknowledged well inside 3 seconds")
        for _ in range(50):
            if self.broker.positions(self.engine.cfg.magic):
                break
            time.sleep(0.05)
        pos = self.broker.positions(self.engine.cfg.magic)
        self.assertEqual(len(pos), 1)
        self.assertEqual((pos[0].sl, pos[0].tp, pos[0].volume), (3880.30, 3920.30, 0.02))
        self.assertEqual(call(self.base + "/tv/" + SECRET, body)[0], 202)          # duplicate delivery
        time.sleep(0.5)
        self.assertEqual(len(self.broker.positions(self.engine.cfg.magic)), 1, "a duplicate must not open a second position")
        code, raw = call(self.base + "/status/" + SECRET)
        status = json.loads(raw)
        self.assertEqual((code, status["mode"], len(status["open_trades"])), (200, "demo", 1))
        self.assertEqual(call(self.base + "/status/nope")[0], 404)


if __name__ == "__main__":
    unittest.main()
