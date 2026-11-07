"""
paper.py – Paper broker: same interface as LiveBroker, no orders sent.

Uses real (public) market data. A simulated position is closed on the first
closed candle after entry that touches its stop or target; when one candle
touches both, the stop is assumed to come first (conservative). Fills are at
the signal price; a taker fee is charged on entry and exit.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

log = logging.getLogger("paper")


def timeframe_ms(tf: str) -> int:
    """'5m' -> 300000; supports m, h, d."""
    unit = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}[tf[-1]]
    return int(tf[:-1]) * unit


@dataclass
class PaperPosition:
    symbol:   str
    side:     str      # "long" | "short"
    qty:      float
    entry:    float
    sl:       float
    tp:       float
    opened_ms: int
    timeframe: str
    last:     float


@dataclass(frozen=True)
class PaperFill:
    symbol: str
    pnl:    float      # net of fees
    ts_ms:  int


class PaperBroker:
    mode = "paper"

    def __init__(self, market: Any, balance: float = 10_000.0, fee_pct: float = 0.05, leverage: int = 10):
        self.market = market            # MarketData (needs closed_ohlcv)
        self.leverage = leverage
        self.fee = fee_pct / 100.0
        self.start_balance = balance
        self.realized = 0.0
        self.positions: Dict[str, PaperPosition] = {}
        self.fills: List[PaperFill] = []

    # ── Setup / account ──────────────────────────────────────────────────────

    async def ensure_markets(self) -> None:
        return None

    async def check_account(self) -> None:
        return None

    def _upnl(self, p: PaperPosition) -> float:
        sign = 1 if p.side == "long" else -1
        return sign * (p.last - p.entry) * p.qty

    async def get_equity(self) -> float:
        return self.start_balance + self.realized + sum(self._upnl(p) for p in self.positions.values())

    async def get_balance(self) -> float:
        used = sum(p.entry * p.qty / self.leverage for p in self.positions.values())
        return max(0.0, await self.get_equity() - used)

    async def get_positions(self) -> List[Dict[str, Any]]:
        await self._update_exits()
        return [{"symbol": p.symbol, "side": p.side, "contracts": p.qty, "entryPrice": p.entry,
                 "unrealizedPnl": self._upnl(p)} for p in self.positions.values()]

    async def income_since(self, since_ms: int, symbol: Optional[str] = None) -> float:
        return sum(f.pnl for f in self.fills if f.ts_ms >= since_ms and (symbol is None or f.symbol == symbol))

    # ── Orders (simulated) ───────────────────────────────────────────────────

    async def open_position(self, symbol: str, side: str, qty: float, sl: float, tp: float,
                            ref_price: float, client_id: Optional[str] = None,
                            timeframe: str = "5m") -> Dict[str, Any]:
        now = int(time.time() * 1000)
        # Exits are checked from the candle that follows the signal candle (the one forming now).
        bar_ms = timeframe_ms(timeframe)
        first_bar = now - now % bar_ms
        self.positions[symbol] = PaperPosition(symbol, side, qty, ref_price, sl, tp, first_bar, timeframe, ref_price)
        self._book(symbol, -ref_price * qty * self.fee, now)
        log.info(f"[PAPER OPEN] {symbol} {side.upper()} qty={qty:.6g} entry={ref_price} sl={sl} tp={tp}")
        return {"symbol": symbol, "side": side, "entry": ref_price, "qty": qty, "sl": sl, "tp": tp, "tp_ok": True}

    def _book(self, symbol: str, pnl: float, ts_ms: int) -> None:
        self.realized += pnl
        self.fills.append(PaperFill(symbol, pnl, ts_ms))

    def _exit(self, p: PaperPosition, price: float, reason: str) -> None:
        sign = 1 if p.side == "long" else -1
        gross = sign * (price - p.entry) * p.qty
        self._book(p.symbol, gross - price * p.qty * self.fee, int(time.time() * 1000))
        self.positions.pop(p.symbol, None)
        log.info(f"[PAPER {reason}] {p.symbol} {p.side.upper()} exit={price} pnl={gross:+.2f} USDT before fees")

    async def _update_exits(self) -> None:
        for p in list(self.positions.values()):
            df = await self.market.closed_ohlcv(p.symbol, p.timeframe, 50)
            bars = df[df["ts_ms"] >= p.opened_ms]
            for _, b in bars.iterrows():
                hit_sl = b["low"] <= p.sl if p.side == "long" else b["high"] >= p.sl
                hit_tp = b["high"] >= p.tp if p.side == "long" else b["low"] <= p.tp
                if hit_sl:              # stop first when both are inside one candle
                    self._exit(p, p.sl, "STOP")
                    break
                if hit_tp:
                    self._exit(p, p.tp, "TARGET")
                    break
            else:
                if len(df):
                    p.last = float(df["close"].iloc[-1])

    async def cancel_orders(self, symbol: str) -> None:
        return None

    async def close_position(self, symbol: str, side: str, contracts: float) -> bool:
        p = self.positions.get(symbol)
        if p:
            self._exit(p, p.last, "CLOSE")
        return True

    async def close_all(self) -> List[str]:
        for sym in list(self.positions):
            await self.close_position(sym, self.positions[sym].side, self.positions[sym].qty)
        return []

    async def close(self) -> None:
        return None
