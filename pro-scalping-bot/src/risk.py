"""
risk.py – Professional Risk Manager
- Position sizing (fixed risk % per trade)
- Daily loss limit  → halts bot if breached
- Drawdown guard    → reduces size after consecutive losses
- Min RR check      → skips low-quality setups
"""

import logging
from dataclasses import dataclass, field
from typing import List

log = logging.getLogger("risk")


@dataclass
class TradeRecord:
    symbol: str
    pnl:    float
    won:    bool


class RiskManager:
    def __init__(
        self,
        risk_pct:          float = 0.01,   # 1% risk per trade
        max_daily_loss:    float = 0.05,   # halt if -5% daily
        max_consec_losses: int   = 3,      # reduce size after 3 losses
        min_rr:            float = 1.8,    # minimum reward:risk ratio
        leverage:          int   = 10,
    ):
        self.risk_pct          = risk_pct
        self.max_daily_loss    = max_daily_loss
        self.max_consec_losses = max_consec_losses
        self.min_rr            = min_rr
        self.leverage          = leverage

        self._daily_pnl:    float           = 0.0
        self._consec_losses: int            = 0
        self._history:       List[TradeRecord] = []
        self._halted:        bool           = False

    # ── Public API ────────────────────────────────────────────────────────────

    def is_halted(self) -> bool:
        return self._halted

    def check_signal(self, entry: float, sl: float, tp: float) -> bool:
        """Returns True if signal passes all risk filters."""
        if self._halted:
            log.warning("Bot halted due to daily loss limit.")
            return False

        rr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
        if rr < self.min_rr:
            log.info(f"Signal rejected: RR={rr:.2f} < min {self.min_rr}")
            return False

        return True

    def position_size(self, balance: float, entry: float, sl: float) -> float:
        """
        Kelly-inspired fixed-fractional sizing.
        Reduces size by 50% after consecutive losses.
        """
        sl_dist = abs(entry - sl)
        if sl_dist <= 0:
            return 0.0

        effective_risk = self.risk_pct
        if self._consec_losses >= self.max_consec_losses:
            effective_risk *= 0.5
            log.info(f"Size reduced 50% after {self._consec_losses} consecutive losses.")

        risk_usd = balance * effective_risk
        notional = risk_usd * self.leverage
        qty      = notional / entry
        return round(qty, 3)

    def record_trade(self, symbol: str, pnl: float, balance: float):
        """Call after every closed trade."""
        won = pnl > 0
        self._history.append(TradeRecord(symbol=symbol, pnl=pnl, won=won))
        self._daily_pnl += pnl

        if won:
            self._consec_losses = 0
        else:
            self._consec_losses += 1

        # Check daily loss limit
        if balance > 0 and abs(self._daily_pnl) / balance >= self.max_daily_loss and self._daily_pnl < 0:
            self._halted = True
            log.critical(
                f"Daily loss limit reached ({self._daily_pnl:.2f} USDT). "
                "Bot halted for today."
            )

        log.info(
            f"Trade recorded: {symbol} pnl={pnl:+.4f} "
            f"daily_pnl={self._daily_pnl:+.4f} "
            f"consec_losses={self._consec_losses}"
        )

    def reset_daily(self):
        """Call at start of each day."""
        self._daily_pnl = 0.0
        self._halted    = False
        log.info("Daily risk counters reset.")

    def stats(self) -> dict:
        total  = len(self._history)
        wins   = sum(1 for t in self._history if t.won)
        losses = total - wins
        total_pnl = sum(t.pnl for t in self._history)
        win_rate  = wins / total * 100 if total else 0
        return {
            "total_trades":   total,
            "wins":           wins,
            "losses":         losses,
            "win_rate":       round(win_rate, 1),
            "total_pnl":      round(total_pnl, 4),
            "daily_pnl":      round(self._daily_pnl, 4),
            "consec_losses":  self._consec_losses,
            "halted":         self._halted,
        }
