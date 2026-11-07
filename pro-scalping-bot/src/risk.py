"""
risk.py – Risk manager.

- Position size from the stop distance: a stop-out loses `risk_pct` of equity
  (before slippage and fees), capped by the margin actually available.
- Daily loss limit from exchange data: the day's realized PnL, fees and funding
  plus open unrealized PnL. It halts new entries when the loss reaches
  `max_daily_loss` of the day's starting equity. The bot then closes all positions.
- Size halved after `max_consec_losses` losing trades in a row.
- Minimum reward:risk filter.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

log = logging.getLogger("risk")


@dataclass(frozen=True)
class TradeRecord:
    symbol: str
    pnl:    float
    won:    bool


class RiskManager:
    def __init__(
        self,
        risk_pct:          float = 0.01,   # equity lost if the stop is hit
        max_daily_loss:    float = 0.05,   # halt at -5% of the day's starting equity
        max_consec_losses: int   = 3,      # halve size after 3 losses in a row
        min_rr:            float = 1.8,    # minimum reward:risk
        leverage:          int   = 10,
        max_margin_frac:   float = 0.9,    # never commit more than 90% of free margin to one order
    ):
        if not 0 < risk_pct <= 0.05:
            raise ValueError(f"risk_pct must be in (0, 0.05], got {risk_pct}")
        if not 0 < max_daily_loss <= 0.2:
            raise ValueError(f"max_daily_loss must be in (0, 0.2], got {max_daily_loss}")
        if not 1 <= leverage <= 50:
            raise ValueError(f"leverage must be in [1, 50], got {leverage}")
        if not 0 < max_margin_frac <= 1:
            raise ValueError(f"max_margin_frac must be in (0, 1], got {max_margin_frac}")
        self.risk_pct          = risk_pct
        self.max_daily_loss    = max_daily_loss
        self.max_consec_losses = max_consec_losses
        self.min_rr            = min_rr
        self.leverage          = leverage
        self.max_margin_frac   = max_margin_frac

        self._daily_pnl:     float             = 0.0
        self._consec_losses: int               = 0
        self._history:       List[TradeRecord] = []
        self._halted:        bool              = False
        self._halt_reason:   str               = ""

    # ── State ─────────────────────────────────────────────────────────────────

    def is_halted(self) -> bool:
        return self._halted

    def halt(self, reason: str) -> None:
        if not self._halted:
            log.critical(f"New entries halted for today: {reason}")
        self._halted = True
        self._halt_reason = reason

    @property
    def halt_reason(self) -> str:
        return self._halt_reason

    # ── Filters and sizing ───────────────────────────────────────────────────

    def check_signal(self, entry: float, sl: float, tp: float) -> bool:
        """True if the signal passes the risk filters."""
        if self._halted:
            return False
        risk = abs(entry - sl)
        if risk <= 0:
            return False
        rr = abs(tp - entry) / risk
        if rr < self.min_rr:
            log.info(f"Signal rejected: RR={rr:.2f} < min {self.min_rr}")
            return False
        return True

    def position_size(self, free_margin: float, equity: float, entry: float, sl: float) -> float:
        """Quantity whose stop-out loses risk_pct of equity, capped by free margin × leverage.
        Returns the raw quantity; the broker applies the exchange's step size and minimums."""
        sl_dist = abs(entry - sl)
        if sl_dist <= 0 or entry <= 0 or equity <= 0:
            return 0.0
        risk = self.risk_pct
        if self._consec_losses >= self.max_consec_losses:
            risk *= 0.5
            log.info(f"Size halved after {self._consec_losses} consecutive losses.")
        qty = equity * risk / sl_dist
        max_notional = max(0.0, free_margin) * self.leverage * self.max_margin_frac
        if qty * entry > max_notional:
            log.info(f"Size capped by free margin: {qty * entry:.2f} → {max_notional:.2f} USDT notional")
            qty = max_notional / entry
        return qty

    # ── Daily loss limit ─────────────────────────────────────────────────────

    def update_daily(self, day_pnl: float, equity_now: float) -> bool:
        """day_pnl = today's realized PnL + fees + funding + open unrealized PnL (exchange data).
        Returns True (and halts entries) when the loss reaches max_daily_loss of the day's starting equity."""
        self._daily_pnl = day_pnl
        start_equity = equity_now - day_pnl
        breached = start_equity > 0 and day_pnl < 0 and -day_pnl / start_equity >= self.max_daily_loss
        if breached:
            self.halt(f"daily loss {day_pnl:+.2f} USDT = {day_pnl / start_equity * 100:.2f}% "
                      f"(limit -{self.max_daily_loss * 100:.1f}%)")
        return breached

    def record_trade(self, symbol: str, pnl: Optional[float]) -> None:
        """Call after every closed trade with its realized PnL (net of fees) from the exchange."""
        if pnl is None:
            log.warning(f"PnL unknown for {symbol}; consecutive-loss counter unchanged.")
            return
        won = pnl > 0
        self._history.append(TradeRecord(symbol=symbol, pnl=pnl, won=won))
        self._consec_losses = 0 if won else self._consec_losses + 1
        log.info(f"Trade recorded: {symbol} pnl={pnl:+.4f} consec_losses={self._consec_losses}")

    def reset_daily(self) -> None:
        """Call at the start of each UTC day."""
        self._daily_pnl = 0.0
        self._halted = False
        self._halt_reason = ""
        log.info("Daily risk counters reset.")

    def stats(self) -> dict:
        total = len(self._history)
        wins = sum(1 for t in self._history if t.won)
        return {
            "total_trades":  total,
            "wins":          wins,
            "losses":        total - wins,
            "win_rate":      round(wins / total * 100, 1) if total else 0,
            "total_pnl":     round(sum(t.pnl for t in self._history), 4),
            "daily_pnl":     round(self._daily_pnl, 4),
            "consec_losses": self._consec_losses,
            "halted":        self._halted,
            "halt_reason":   self._halt_reason,
        }
