"""
strategy.py – Pro Scalping Strategy
5 confirmations required for entry:
  1. EMA Trend alignment    (9 > 21 > 50 for long)
  2. EMA Cross              (fresh crossover)
  3. RSI momentum zone      (45–70 long | 30–55 short)
  4. MACD confirmation      (histogram positive for long)
  5. Volume spike           (ratio > 1.2)

SL  = 1.5 × ATR  (below/above nearest structure)
TP  = 3.0 × ATR  (Risk:Reward = 1:2)
"""

from typing import Optional, Dict, Any
import pandas as pd
from indicators import apply_all


class ProScalpingStrategy:

    def __init__(
        self,
        # EMA
        ema_fast: int   = 9,
        ema_mid:  int   = 21,
        ema_slow: int   = 50,
        # RSI
        rsi_long_min:  float = 45.0,
        rsi_long_max:  float = 70.0,
        rsi_short_min: float = 30.0,
        rsi_short_max: float = 55.0,
        # Volume
        vol_min: float = 1.2,
        # SL / TP
        sl_atr_mult: float = 1.5,
        tp_atr_mult: float = 3.0,
    ):
        self.ema_fast      = ema_fast
        self.ema_mid       = ema_mid
        self.ema_slow      = ema_slow
        self.rsi_long_min  = rsi_long_min
        self.rsi_long_max  = rsi_long_max
        self.rsi_short_min = rsi_short_min
        self.rsi_short_max = rsi_short_max
        self.vol_min       = vol_min
        self.sl_atr_mult   = sl_atr_mult
        self.tp_atr_mult   = tp_atr_mult

    # ── Public ────────────────────────────────────────────────────────────────

    def generate(self, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        if len(df) < 60:
            return None

        df   = apply_all(df)
        last = df.iloc[-1]
        prev = df.iloc[-2]

        price = float(last["close"])
        atr_v = float(last["atr"])

        # ── Shared filters ────────────────────────────────────────────────────
        vol_ok = float(last["vol_ratio"]) >= self.vol_min

        # EMA values
        ef  = float(last["ema9"]);   pef = float(prev["ema9"])
        em  = float(last["ema21"]);  pem = float(prev["ema21"])
        es  = float(last["ema50"])

        # MACD
        hist      = float(last["macd_hist"])
        prev_hist = float(prev["macd_hist"])

        # RSI
        rsi_v = float(last["rsi"])

        # ── LONG: 5 confirmations ─────────────────────────────────────────────
        long_trend  = ef > em > es                          # 1. Trend aligned
        long_cross  = pef < pem and ef > em                 # 2. Fresh EMA cross
        long_rsi    = self.rsi_long_min <= rsi_v <= self.rsi_long_max   # 3. RSI zone
        long_macd   = hist > 0 and hist > prev_hist         # 4. MACD rising
        long_vol    = vol_ok                                 # 5. Volume spike

        if long_trend and long_cross and long_rsi and long_macd and long_vol:
            sl = price - self.sl_atr_mult * atr_v
            tp = price + self.tp_atr_mult * atr_v
            score = self._score(long_trend, long_cross, long_rsi, long_macd, long_vol)
            return {
                "signal":    "long",
                "entry":     round(price, 6),
                "sl":        round(sl, 6),
                "tp":        round(tp, 6),
                "rsi":       round(rsi_v, 1),
                "vol_ratio": round(float(last["vol_ratio"]), 2),
                "score":     score,
            }

        # ── SHORT: 5 confirmations ────────────────────────────────────────────
        short_trend = ef < em < es                           # 1. Trend aligned
        short_cross = pef > pem and ef < em                  # 2. Fresh EMA cross
        short_rsi   = self.rsi_short_min <= rsi_v <= self.rsi_short_max  # 3. RSI zone
        short_macd  = hist < 0 and hist < prev_hist          # 4. MACD falling
        short_vol   = vol_ok                                  # 5. Volume spike

        if short_trend and short_cross and short_rsi and short_macd and short_vol:
            sl = price + self.sl_atr_mult * atr_v
            tp = price - self.tp_atr_mult * atr_v
            score = self._score(short_trend, short_cross, short_rsi, short_macd, short_vol)
            return {
                "signal":    "short",
                "entry":     round(price, 6),
                "sl":        round(sl, 6),
                "tp":        round(tp, 6),
                "rsi":       round(rsi_v, 1),
                "vol_ratio": round(float(last["vol_ratio"]), 2),
                "score":     score,
            }

        return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _score(*conditions: bool) -> int:
        """Returns number of confirmations passed (max 5)."""
        return sum(conditions)
