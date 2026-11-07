"""
bot.py – Pro Scalping Bot
5-confirmation strategy | exchange-backed risk limits | paper trading by default.
Logs → Railway dashboard.

Modes (TRADING_MODE): "paper" (default, no orders sent) or "live" (real orders,
needs BINANCE_API_KEY and BINANCE_API_SECRET). See README.md.
"""

import asyncio
import json
import logging
import os
import re
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import ccxt.async_support as ccxt
import pandas as pd
import yaml

from broker import LiveBroker, OrderError, OrderNotSent
from paper import PaperBroker
from risk import RiskManager
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

class ConfigError(ValueError):
    """A setting is missing or outside its safe range."""


# key: (environment variable, type, default, minimum, maximum)
BOUNDS: Dict[str, tuple] = {
    "leverage":          ("LEVERAGE",          int,   10,     1,     20),
    "risk_pct":          ("RISK_PCT",          float, 0.01,   0.001, 0.02),
    "max_daily_loss":    ("MAX_DAILY_LOSS",    float, 0.05,   0.005, 0.10),
    "max_positions":     ("MAX_POS",           int,   5,      1,     10),
    "loop_seconds":      ("LOOP_SECONDS",      int,   60,     10,    3600),
    "max_failed_cycles": ("MAX_FAILED_CYCLES", int,   3,      1,     20),
    "paper_balance":     ("PAPER_BALANCE",     float, 10_000, 100,   1e9),
    "paper_fee_pct":     ("PAPER_FEE_PCT",     float, 0.05,   0.0,   1.0),
}


def load_config(path: str = "config.yaml") -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # Railway variables take priority over the yaml file; every value is range-checked.
    for key, (env, cast, default, lo, hi) in BOUNDS.items():
        raw = os.getenv(env, cfg.get(key, default))
        try:
            value = cast(raw)
        except (TypeError, ValueError):
            raise ConfigError(f"{key}={raw!r} is not a valid number (set by {env} or config.yaml)") from None
        if not lo <= value <= hi:
            raise ConfigError(f"{key}={value} is outside the safe range [{lo}, {hi}] (set by {env} or config.yaml)")
        cfg[key] = value

    mode = str(os.getenv("TRADING_MODE", cfg.get("mode", "paper"))).strip().lower()
    if mode not in ("paper", "live"):
        raise ConfigError(f"TRADING_MODE must be 'paper' or 'live', got {mode!r}")
    cfg["mode"] = mode
    if not cfg.get("symbols"):
        raise ConfigError("config.yaml has no symbols")
    return cfg


# ─── Helpers ──────────────────────────────────────────────────────────────────

def utc_midnight_ms(now: Optional[datetime] = None) -> int:
    now = now or datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp() * 1000)


def client_order_id(symbol: str, bar_ms: int) -> str:
    """Deterministic id per symbol and signal candle: Binance rejects a second order with the same id."""
    base = re.sub(r"[^A-Za-z0-9]", "", symbol.split(":")[0])[:16]
    return f"psb{base}{bar_ms // 1000}"[:36]


# ─── Market data ──────────────────────────────────────────────────────────────

class MarketData:
    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.ex = ccxt.binanceusdm({
            "apiKey":          api_key,
            "secret":          api_secret,
            "enableRateLimit": True,
            "options":         {"defaultType": "future"},
        })

    async def closed_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """Closed candles only: the exchange's last row is the candle still forming, so it is dropped."""
        rows = await self.ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit + 1)
        df = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low", "close", "volume"])
        bar_ms = self.ex.parse_timeframe(timeframe) * 1000
        if len(df) and int(df["ts_ms"].iloc[-1]) + bar_ms > self.ex.milliseconds():
            df = df.iloc[:-1]
        df = df.reset_index(drop=True)
        df["timestamp"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
        return df

    async def close(self) -> None:
        await self.ex.close()


# ─── Bot ──────────────────────────────────────────────────────────────────────

class ProScalpingBot:
    def __init__(self, cfg: Dict[str, Any], broker: Any = None, market: Any = None):
        self.cfg = cfg
        self.symbols: List[Dict[str, Any]] = cfg["symbols"]
        self.mode: str = cfg.get("mode", "paper")

        api_key = os.getenv("BINANCE_API_KEY", "")
        api_secret = os.getenv("BINANCE_API_SECRET", "")
        self.market = market or MarketData(api_key, api_secret)
        if broker is not None:
            self.broker = broker
        elif self.mode == "live":
            if not api_key or not api_secret:
                raise ConfigError("TRADING_MODE=live needs BINANCE_API_KEY and BINANCE_API_SECRET")
            self.broker = LiveBroker(api_key, api_secret, leverage=cfg["leverage"])
        else:
            self.broker = PaperBroker(self.market, cfg.get("paper_balance", 10_000),
                                      cfg.get("paper_fee_pct", 0.05), cfg["leverage"])

        self.strategy = ProScalpingStrategy(
            sl_atr_mult=cfg.get("sl_atr_mult", 1.5),
            tp_atr_mult=cfg.get("tp_atr_mult", 3.0),
            vol_min=cfg.get("vol_min", 1.2),
        )
        self.risk = RiskManager(
            risk_pct=cfg["risk_pct"],
            max_daily_loss=cfg["max_daily_loss"],
            max_consec_losses=cfg.get("max_consec_losses", 3),
            min_rr=cfg.get("min_rr", 1.8),
            leverage=cfg["leverage"],
        )

        # symbol → trade info; rebuilt from the exchange on every sync (survives restarts)
        self.open_pos: Dict[str, Dict[str, Any]] = {}
        self.positions: Dict[str, Dict[str, Any]] = {}

        self.cycle = 0
        self.failed_cycles = 0
        self.order_errors_today = 0
        self.flattened_today = False
        self.day_start_equity: Optional[float] = None
        self.last_day = datetime.now(timezone.utc).date()
        self.stop_event = asyncio.Event()

    # ── Startup ───────────────────────────────────────────────────────────────

    async def startup(self) -> None:
        await self.broker.check_account()
        if os.getenv("KILL_SWITCH", "").strip() == "1":
            remaining = await self.broker.close_all()
            self.risk.halt("KILL_SWITCH=1")
            log.critical(f"KILL_SWITCH=1: all positions closed (still open: {remaining or 'none'}). No new trades.")
        try:
            await self._sync()
        except Exception as e:
            self.failed_cycles = 1
            log.error(f"Startup sync failed: {e} — no entries until the account state can be read.")

    # ── Sync with exchange ────────────────────────────────────────────────────

    async def _sync(self) -> None:
        """Reconcile with the exchange (the source of truth). Raises if positions cannot be read."""
        current = {p["symbol"]: p for p in await self.broker.get_positions()}

        for sym, p in current.items():
            if sym not in self.open_pos:
                self.open_pos[sym] = {"symbol": sym, "side": p.get("side"), "qty": float(p.get("contracts") or 0),
                                      "entry": float(p.get("entryPrice") or 0), "opened_at": time.time(),
                                      "adopted": True}
                log.warning(f"[ADOPT] {sym} {p.get('side')} position found on the exchange; "
                            "no new entry on this symbol while it is open.")

        for sym in list(self.open_pos):
            if sym in current:
                continue
            opened = self.open_pos.pop(sym)
            await self.broker.cancel_orders(sym)   # the other leg (stop or target) is now an orphan
            duration = round((time.time() - opened["opened_at"]) / 60, 1)
            pnl: Optional[float] = None
            if not opened.get("adopted"):
                try:
                    pnl = await self.broker.income_since(int(opened["opened_at"] * 1000) - 60_000, sym)
                except Exception as e:
                    log.warning(f"PnL lookup failed for {sym}: {e}")
                self.risk.record_trade(sym, pnl)
            log.info(f"[CLOSED] {sym} side={opened['side']} duration={duration}m "
                     f"pnl={'unknown' if pnl is None else f'{pnl:+.4f} USDT'}")

        self.positions = current

    # ── Daily loss limit ─────────────────────────────────────────────────────

    async def _daily_guard(self) -> None:
        equity = await self.broker.get_equity()
        upnl = sum(float(p.get("unrealizedPnl") or 0) for p in self.positions.values())
        try:
            day_pnl = await self.broker.income_since(utc_midnight_ms()) + upnl
        except Exception as e:
            if self.day_start_equity is None:
                self.day_start_equity = equity
            day_pnl = equity - self.day_start_equity
            log.warning(f"Income ledger unavailable ({e}); daily loss measured from equity "
                        f"{self.day_start_equity:.2f} at first check (resets if the bot restarts).")

        if self.risk.update_daily(day_pnl, equity) and not self.flattened_today:
            remaining = await self.broker.close_all()
            self.flattened_today = not remaining
            if remaining:
                log.critical(f"Daily loss limit hit; still open after close-all: {remaining}. Retrying next cycle.")
            else:
                log.critical("Daily loss limit hit; all positions closed. No new trades until 00:00 UTC.")

    def _check_daily_reset(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today == self.last_day:
            return
        self.risk.reset_daily()
        self.last_day = today
        self.flattened_today = False
        self.order_errors_today = 0
        self.day_start_equity = None
        if os.getenv("KILL_SWITCH", "").strip() == "1":
            self.risk.halt("KILL_SWITCH=1")
        log.info("═" * 55)
        log.info("  New UTC day — daily risk counters reset.")
        log.info("═" * 55)

    # ── Per-symbol ────────────────────────────────────────────────────────────

    async def _process(self, sym_cfg: Dict[str, Any]) -> None:
        symbol = sym_cfg["symbol"]
        timeframe = sym_cfg.get("timeframe", "5m")
        limit = sym_cfg.get("limit", 150)

        if symbol in self.open_pos or symbol in self.positions:
            return
        if len(self.open_pos) >= self.cfg["max_positions"]:
            return
        if self.risk.is_halted():
            return

        df = await self.market.closed_ohlcv(symbol, timeframe, limit)
        sig = self.strategy.generate(df)
        if not sig:
            return
        if not self.risk.check_signal(sig["entry"], sig["sl"], sig["tp"]):
            return

        equity = await self.broker.get_equity()
        free = await self.broker.get_balance()
        qty = self.risk.position_size(free, equity, sig["entry"], sig["sl"])
        if qty <= 0:
            log.warning(f"Zero size for {symbol} (equity={equity:.2f}, free={free:.2f})")
            return

        kwargs: Dict[str, Any] = dict(symbol=symbol, side=sig["signal"], qty=qty, sl=sig["sl"], tp=sig["tp"],
                                      ref_price=sig["entry"],
                                      client_id=client_order_id(symbol, int(df["ts_ms"].iloc[-1])))
        if self.broker.mode == "paper":
            kwargs["timeframe"] = timeframe
        trade = await self.broker.open_position(**kwargs)

        self.open_pos[symbol] = {**trade, "score": sig["score"], "rsi": sig["rsi"],
                                 "vol_ratio": sig["vol_ratio"], "opened_at": time.time()}
        log.info(f"  ✦ Signal score={sig['score']}/5  RSI={sig['rsi']}  vol×{sig['vol_ratio']}")

    # ── Run ───────────────────────────────────────────────────────────────────

    async def run_once(self) -> None:
        self._check_daily_reset()
        try:
            await self._sync()
            await self._daily_guard()
        except Exception as e:
            self.failed_cycles += 1
            say = log.critical if self.failed_cycles >= self.cfg["max_failed_cycles"] else log.error
            say(f"Account state unreadable ({self.failed_cycles} cycle(s) in a row): {e} — "
                "no new entries until it recovers.")
            return
        if self.failed_cycles:
            log.info(f"Account state readable again after {self.failed_cycles} failed cycle(s).")
        self.failed_cycles = 0

        for sym in self.symbols:
            if self.stop_event.is_set():
                break
            try:
                await self._process(sym)
            except OrderNotSent as e:
                log.warning(str(e))
            except OrderError as e:
                self.order_errors_today += 1
                log.critical(f"[ORDER ERROR] {e}")
                if self.order_errors_today >= 2:
                    self.risk.halt(f"{self.order_errors_today} order errors today")
            except Exception as e:
                log.error(f"Error [{sym.get('symbol')}]: {e}")

    async def run_forever(self) -> None:
        log.info("═" * 55)
        log.info(f"  ⚡ Pro Scalping Bot  |  {self.mode.upper()}  |  5m")
        if self.mode == "paper":
            log.info("  PAPER MODE: no orders are sent. Set TRADING_MODE=live to trade real money.")
        log.info(f"  Pairs      : {len(self.symbols)} symbols")
        log.info(f"  Leverage   : {self.cfg['leverage']}x")
        log.info(f"  Risk/trade : {self.cfg['risk_pct'] * 100:.1f}% of equity at the stop")
        log.info(f"  Max DD/day : {self.cfg['max_daily_loss'] * 100:.1f}% (then close all + halt)")
        log.info(f"  Max pos    : {self.cfg['max_positions']}")
        log.info(f"  Loop       : {self.cfg['loop_seconds']}s")
        log.info("  Strategy   : 5-confirmation EMA+RSI+MACD+VOL on closed candles")
        log.info("═" * 55)

        await self.startup()
        while not self.stop_event.is_set():
            self.cycle += 1
            s = self.risk.stats()
            log.info(f"── Cycle #{self.cycle}  open={len(self.open_pos)}  trades={s['total_trades']}  "
                     f"win={s['win_rate']}%  daily_pnl={s['daily_pnl']:+.2f}  halted={s['halted']} ──")
            await self.run_once()
            if self.cycle % 20 == 0:
                log.info(f"[STATS] {json.dumps(self.risk.stats())}")
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.cfg["loop_seconds"])
            except asyncio.TimeoutError:
                pass

        log.info("Stopping. Open positions keep their exchange stop-loss and take-profit orders.")
        if os.getenv("CLOSE_ON_SHUTDOWN", "").strip() == "1":
            remaining = await self.broker.close_all()
            log.warning(f"CLOSE_ON_SHUTDOWN=1: closed all positions (still open: {remaining or 'none'}).")

    async def close(self) -> None:
        await self.market.close()
        await self.broker.close()


# ─── Entry ────────────────────────────────────────────────────────────────────

async def main() -> None:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--once", action="store_true")
    args = p.parse_args()

    try:
        cfg = load_config(args.config)
        bot = ProScalpingBot(cfg)
    except ConfigError as e:
        log.critical(f"Config error: {e}")
        sys.exit(2)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, bot.stop_event.set)
        except NotImplementedError:  # Windows
            pass

    try:
        if args.once:
            await bot.startup()
            await bot.run_once()
            log.info(json.dumps(bot.risk.stats(), indent=2))
        else:
            await bot.run_forever()
    finally:
        await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
