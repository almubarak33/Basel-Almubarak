"""Configuration loaded from a TOML file. Risk settings can be changed here without touching code."""
import os
import tomllib
from dataclasses import dataclass, field


@dataclass
class Risk:
    risk_pct: float = 0.5                  # percent of equity lost if the stop is hit
    max_daily_loss_pct: float = 2.0        # lock for the rest of the day and flatten
    max_total_loss_pct: float = 10.0       # lock until an operator resets it
    max_open_positions: int = 2
    max_trades_per_day: int = 10
    max_notional_x_equity: float = 1.0     # position value / equity
    max_spread_frac_of_stop: float = 0.12  # spread must be a small part of the stop distance
    max_lots: float = 1.0


@dataclass
class Source:
    enabled: bool = False
    max_age_sec: float = 20.0              # reject a signal older than this
    max_chase_frac: float = 0.25           # reject if price moved more than this fraction of the risk from the model entry
    tp_field: str = "tp1"                  # which target of the message becomes the take-profit
    max_hold_min: float = 0.0              # 0 = use the message's own "expire" time


@dataclass
class Config:
    mode: str = "monitor"                  # monitor (no orders) | demo | live
    live_armed: bool = False
    magic: int = 20261114
    db_path: str = "sabika_bridge.sqlite"
    host: str = "127.0.0.1"
    port: int = 8787
    secret: str = ""
    max_body_bytes: int = 65536
    heartbeat_timeout_sec: float = 420.0
    risk: Risk = field(default_factory=Risk)
    symbols: dict = field(default_factory=dict)    # alert symbol -> broker symbol
    sources: dict = field(default_factory=dict)    # source name -> Source

    def validate(self):
        if self.mode not in ("monitor", "demo", "live"):
            raise ValueError("bridge.mode must be monitor, demo or live")
        r = self.risk
        if not 0 < r.risk_pct <= 1.0:
            raise ValueError("risk.risk_pct must be above 0 and at most 1.0 (hard ceiling)")
        if not 0 < r.max_daily_loss_pct <= 5.0:
            raise ValueError("risk.max_daily_loss_pct must be above 0 and at most 5")
        if not 0 < r.max_total_loss_pct <= 20.0:
            raise ValueError("risk.max_total_loss_pct must be above 0 and at most 20")
        if r.max_open_positions < 1 or r.max_trades_per_day < 1:
            raise ValueError("risk.max_open_positions and risk.max_trades_per_day must be at least 1")
        if not 0 < r.max_notional_x_equity <= 5.0:
            raise ValueError("risk.max_notional_x_equity must be above 0 and at most 5")
        if len(self.secret) < 16:
            raise ValueError("ingress.secret (or env SABIKA_SECRET) must be at least 16 characters")
        for name, s in self.sources.items():
            if s.tp_field not in ("tp1", "tp2", "tp3", "tp4"):
                raise ValueError("sources.%s.tp_field must be tp1..tp4" % name)
        return self


def load(path):
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    b, i = raw.get("bridge", {}), raw.get("ingress", {})
    cfg = Config(
        mode=b.get("mode", "monitor"), live_armed=bool(b.get("live_armed", False)), magic=int(b.get("magic", 20261114)),
        db_path=b.get("db_path", "sabika_bridge.sqlite"), heartbeat_timeout_sec=float(b.get("heartbeat_timeout_sec", 420)),
        host=i.get("host", "127.0.0.1"), port=int(i.get("port", 8787)),
        secret=os.environ.get("SABIKA_SECRET") or i.get("secret", ""), max_body_bytes=int(i.get("max_body_bytes", 65536)),
        risk=Risk(**raw.get("risk", {})),
        symbols={k: v["broker_symbol"] for k, v in raw.get("symbols", {}).items()},
        sources={k: Source(**v) for k, v in raw.get("sources", {}).items()},
    )
    return cfg.validate()
