"""SQLite journal: every message and every decision is recorded; state survives restarts."""
import json
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
  id TEXT PRIMARY KEY, src TEXT, kind TEXT, received_at REAL, raw TEXT,
  status TEXT, reason TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS trades(
  signal_id TEXT PRIMARY KEY, src TEXT, ticket INTEGER, symbol TEXT, side TEXT, volume REAL,
  model_entry REAL, fill_price REAL, sl REAL, tp REAL, risk_money REAL, planned_loss REAL,
  day TEXT, opened_at REAL, expire_at REAL, closed_at REAL, close_reason TEXT);
CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT);
"""


class Store:
    def __init__(self, path):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def _run(self, sql, args=()):
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur

    def _all(self, sql, args=()):
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    # ---- messages
    def record_message(self, msg_id, src, kind, received_at, raw):
        """Insert a message; return False if this id was already seen (duplicate)."""
        try:
            self._run("INSERT INTO messages(id,src,kind,received_at,raw,status) VALUES(?,?,?,?,?,?)",
                      (msg_id, src, kind, received_at, json.dumps(raw, separators=(",", ":")), "received"))
            return True
        except sqlite3.IntegrityError:
            return False

    def set_status(self, msg_id, status, reason="", detail=None):
        self._run("UPDATE messages SET status=?, reason=?, detail=? WHERE id=?",
                  (status, reason, json.dumps(detail or {}, separators=(",", ":")), msg_id))

    def recent_messages(self, n=20):
        return self._all("SELECT id,src,kind,received_at,status,reason,detail FROM messages ORDER BY received_at DESC LIMIT ?", (n,))

    # ---- trades
    def add_trade(self, **t):
        cols = ",".join(t.keys())
        self._run("INSERT INTO trades(%s) VALUES(%s)" % (cols, ",".join("?" * len(t))), tuple(t.values()))

    def open_trades(self):
        return self._all("SELECT * FROM trades WHERE closed_at IS NULL")

    def trades_on_day(self, day):
        return self._all("SELECT * FROM trades WHERE day=?", (day,))

    def close_trade(self, signal_id, when, reason):
        self._run("UPDATE trades SET closed_at=?, close_reason=? WHERE signal_id=? AND closed_at IS NULL", (when, reason, signal_id))

    # ---- state
    def get(self, key, default=None):
        rows = self._all("SELECT value FROM state WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set(self, key, value):
        self._run("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, json.dumps(value)))
