"""Parsing and validation of incoming alert messages (contract version 1)."""
import math
from dataclasses import dataclass, field


class SignalError(Exception):
    """Raised with a short reason code when a message is not acceptable."""


@dataclass
class Signal:
    id: str
    src: str
    sym: str
    tf: str
    side: str
    t_ms: int
    entry: float
    sl: float
    targets: dict = field(default_factory=dict)   # {"tp1": price, ...}
    expire_ms: int = 0
    ref: float = 0.0


@dataclass
class Heartbeat:
    src: str
    sym: str
    t_ms: int
    fields: dict = field(default_factory=dict)


def _num(msg, key, required=True):
    v = msg.get(key)
    if v is None:
        if required:
            raise SignalError("missing_" + key)
        return 0.0
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise SignalError("bad_" + key)
    return float(v)


def _text(msg, key, max_len=80):
    v = msg.get(key)
    if not isinstance(v, str) or not v or len(v) > max_len:
        raise SignalError("bad_" + key)
    return v


def parse(msg):
    """Return a Signal or a Heartbeat; raise SignalError(reason) otherwise."""
    if not isinstance(msg, dict):
        raise SignalError("not_an_object")
    if msg.get("v") != 1:
        raise SignalError("bad_version")
    kind = msg.get("type")
    src = _text(msg, "src", 24)
    sym = _text(msg, "sym", 40)
    t_ms = int(_num(msg, "t"))
    if kind == "hb":
        extra = {k: v for k, v in msg.items() if k not in ("v", "type", "src", "sym", "t")}
        return Heartbeat(src, sym, t_ms, extra)
    if kind != "entry":
        raise SignalError("bad_type")
    side = msg.get("side")
    if side not in ("buy", "sell"):
        raise SignalError("bad_side")
    entry = _num(msg, "entry")
    sl = _num(msg, "sl")
    if entry <= 0 or sl <= 0:
        raise SignalError("bad_price")
    sign = 1 if side == "buy" else -1
    if sign * (entry - sl) <= 0:
        raise SignalError("stop_on_wrong_side")
    targets = {}
    for key in ("tp1", "tp2", "tp3", "tp4"):
        if key in msg:
            tp = _num(msg, key)
            if sign * (tp - entry) <= 0:
                raise SignalError("target_on_wrong_side")
            targets[key] = tp
    tf = msg.get("tf")
    tf = str(tf) if isinstance(tf, (int, str)) and not isinstance(tf, bool) else ""
    return Signal(_text(msg, "id"), src, sym, tf, side, t_ms, entry, sl, targets,
                  int(_num(msg, "expire", required=False)), _num(msg, "ref", required=False))
