"""
bot.py – Pro Scalping Bot
5-confirmation strategy | Dynamic risk management | 30 pairs
Logs → Railway Dashboard
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Set

import ccxt.async_support as ccxt
import pandas as pd
import yaml

from broker   import LiveBroker
from risk     import RiskManager
from strategy import ProScalpingStrategy

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bot")


# ─── Config ───────────────────────────────────────────────────────────────────

def load_config(path: str = "config.yaml") -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # Railway env vars take priority over yaml
    cfg["leverage"]        = int(os.getenv("LEVERAGE",       cfg.get("leverage",        10)))
    cfg["risk_pct"]        = float(os.getenv("RISK_PCT",     cfg.get("risk_pct",        0.01)))
    cfg["max_daily_loss"]  = float(os.getenv("MAX_DAILY_LOSS", cfg.get("max_daily_loss", 0.05)))
    cfg["max_positions"]   = int(os.getenv("MAX_POS",        cfg.get("max_positions",   5)))
    cfg["loop_seconds"]    = int(os.getenv("LOOP_SECONDS",   cfg.get("loop_seconds",    60)))
    return cfg


# ─── Market data ──────────────────────────────────────────────────────────────

class MarketData:
    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.ex = ccxt.binanceusdm({
            "apiKey":          api_key,
            "secret":          api_secret,
            "enableRateLimit": True,
            "options":         {"defaultType": "future"},
        })

    async def ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        rows = await self.ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df   = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df

    async def close(self):
        await self.ex.close()


# ─── Bot ──────────────────────────────────────────────────────────────────────

class ProScalpingBot:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg     = cfg
        self.symbols: List[Dict[str, Any]] = cfg["symbols"]

        api_key    = os.getenv("BINANCE_API_KEY",    "")
        api_secret = os.getenv("BINANCE_API_SECRET", "")

        self.market   = MarketData(api_key, api_secret)
        self.broker   = LiveBroker(api_key, api_secret, leverage=cfg["leverage"])
        self.strategy = ProScalpingStrategy(
            sl_atr_mult = cfg.get("sl_atr_mult", 1.5),
            tp_atr_mult = cfg.get("tp_atr_mult", 3.0),
            vol_min     = cfg.get("vol_min",     1.2),
        )
        self.risk = RiskManager(
            risk_pct          = cfg["risk_pct"],
            max_daily_loss    = cfg["max_daily_loss"],
            max_consec_losses = cfg.get("max_consec_losses", 3),
            min_rr            = cfg.get("min_rr",            1.8),
            leverage          = cfg["leverage"],
        )

        # symbol → open trade info
        self.open_pos: Dict[str, Dict[str, Any]] = {}

        # Cycle stats
        self.cycle    = 0
        self.errors   = 0
        self.last_day = datetime.now(timezone.utc).date()

    # ── Per-symbol ────────────────────────────────────────────────────────────

    async def _process(self, sym_cfg: Dict[str, Any]):
        symbol    = sym_cfg["symbol"]
        timeframe = sym_cfg.get("timeframe", "5m")
        limit     = sym_cfg.get("limit",     150)

        # Already in position
        if symbol in self.open_pos:
            return

        # Max positions reached
        if len(self.open_pos) >= self.cfg["max_positions"]:
            return

        # Bot halted by risk manager
        if self.risk.is_halted():
            return

        df  = await self.market.ohlcv(symbol, timeframe, limit)
        sig = self.strategy.generate(df)

        if not sig:
            return

        # Risk filter
        if not self.risk.check_signal(sig["entry"], sig["sl"], sig["tp"]):
            return

        balance = await self.broker.get_balance()
        qty     = self.risk.position_size(balance, sig["entry"], sig["sl"])

        if qty <= 0:
            log.warning(f"Zero qty for {symbol}")
            return

        trade = await self.broker.open_position(
            symbol = symbol,
            side   = sig["signal"],
            qty    = qty,
            sl     = sig["sl"],
            tp     = sig["tp"],
        )

        self.open_pos[symbol] = {
            **trade,
            "score":     sig["score"],
            "rsi":       sig["rsi"],
            "vol_ratio": sig["vol_ratio"],
            "opened_at": time.time(),
        }

        log.info(
            f"  ✦ Signal score={sig['score']}/5  "
            f"RSI={sig['rsi']}  vol×{sig['vol_ratio']}"
        )

    # ── Sync with exchange ────────────────────────────────────────────────────

    async def _sync(self):
        if not self.open_pos:
            return

        live      = await self.broker.get_positions()
        live_syms: Set[str] = {p["symbol"] for p in live}

        for sym in list(self.open_pos):
            if sym not in live_syms:
                opened   = self.open_pos.pop(sym)
                duration = round((time.time() - opened["opened_at"]) / 60, 1)
                # We can't know exact PnL here without more API calls,
                # so just log the close — risk.record_trade called by webhook/future
                log.info(
                    f"[CLOSED] {sym}  "
                    f"side={opened['side']}  duration={duration}m"
                )

    # ── Daily reset ───────────────────────────────────────────────────────────

    def _check_daily_reset(self):
        today = datetime.now(timezone.utc).date()
        if today != self.last_day:
            self.risk.reset_daily()
            self.last_day = today
            log.info("═" * 55)
            log.info("  New day — daily risk counters reset.")
            log.info("═" * 55)

    # ── Run ───────────────────────────────────────────────────────────────────

    async def run_once(self):
        self._check_daily_reset()
        await self._sync()

        for sym in self.symbols:
            try:
                await self._process(sym)
            except Exception as e:
                self.errors += 1
                log.error(f"Error [{sym.get('symbol')}]: {e}")

    async def run_forever(self):
        log.info("═" * 55)
        log.info("  ⚡ Pro Scalping Bot  |  LIVE  |  5m")
        log.info(f"  Pairs      : {len(self.symbols)} symbols")
        log.info(f"  Leverage   : {self.cfg['leverage']}x")
        log.info(f"  Risk/trade : {self.cfg['risk_pct']*100:.1f}%")
        log.info(f"  Max DD/day : {self.cfg['max_daily_loss']*100:.1f}%")
        log.info(f"  Max pos    : {self.cfg['max_positions']}")
        log.info(f"  Loop       : {self.cfg['loop_seconds']}s")
        log.info(f"  Strategy   : 5-confirmation EMA+RSI+MACD+VOL")
        log.info("═" * 55)

        while True:
            self.cycle += 1
            s = self.risk.stats()
            log.info(
                f"── Cycle #{self.cycle}  "
                f"open={len(self.open_pos)}  "
                f"trades={s['total_trades']}  "
                f"win={s['win_rate']}%  "
                f"daily_pnl={s['daily_pnl']:+.2f}  "
                f"halted={s['halted']} ──"
            )

            await self.run_once()

            # Print full stats every 20 cycles
            if self.cycle % 20 == 0:
                log.info(f"[STATS] {json.dumps(s)}")

            await asyncio.sleep(self.cfg["loop_seconds"])

    async def close(self):
        await self.market.close()
        await self.broker.close()


# ─── Entry ────────────────────────────────────────────────────────────────────

async def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--once",   action="store_true")
    args = p.parse_args()

    cfg = load_config(args.config)
    bot = ProScalpingBot(cfg)

    try:
        if args.once:
            await bot.run_once()
            log.info(json.dumps(bot.risk.stats(), indent=2))
        else:
            await bot.run_forever()
    finally:
        await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
