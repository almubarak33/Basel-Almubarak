"""Safety tests for the bot with a fake exchange (no network, no real orders).

Run: pip install -r requirements-dev.txt && pytest -q
"""

import asyncio
import time
from typing import Any, Dict, List, Optional

import pandas as pd
import pytest

from bot import ConfigError, MarketData, ProScalpingBot, load_config, utc_midnight_ms
from broker import LiveBroker, OrderError, OrderNotSent
from paper import PaperBroker
from risk import RiskManager

SYM = "BTC/USDT:USDT"


# ─── Fakes ────────────────────────────────────────────────────────────────────

class FakeExchange:
    """The ccxt methods the broker uses, with scriptable failures."""

    def __init__(self) -> None:
        self.orders: List[Dict[str, Any]] = []
        self.positions: List[Dict[str, Any]] = []
        self.ledger: List[Dict[str, Any]] = []
        self.equity = 10_000.0
        self.free = 10_000.0
        self.fail_types: set = set()
        self.fill_price: Optional[float] = None
        self.positions_error: Optional[Exception] = None
        self.cancelled: List[str] = []
        self.hedged = False

    async def load_markets(self) -> None:
        return None

    def market(self, symbol: str) -> Dict[str, Any]:
        return {"id": symbol.split("/")[0] + "USDT", "limits": {"amount": {"min": 0.001}, "cost": {"min": 5}}}

    def amount_to_precision(self, symbol: str, qty: float) -> str:
        q = int(qty * 1000) / 1000
        if q < 0.001:
            raise ValueError("amount below minimum")
        return f"{q:.3f}"

    def price_to_precision(self, symbol: str, price: float) -> str:
        return f"{price:.2f}"

    async def fetch_position_mode(self) -> Dict[str, Any]:
        return {"hedged": self.hedged}

    async def set_leverage(self, *a: Any) -> None:
        return None

    async def set_margin_mode(self, *a: Any) -> None:
        return None

    async def fetch_balance(self) -> Dict[str, Any]:
        return {"USDT": {"free": self.free, "total": self.equity}, "info": {"totalMarginBalance": str(self.equity)}}

    async def fetch_positions(self) -> List[Dict[str, Any]]:
        if self.positions_error:
            raise self.positions_error
        return list(self.positions)

    async def fetch_ledger(self, code: str, since: int, limit: int) -> List[Dict[str, Any]]:
        return [e for e in self.ledger if e["info"]["time"] >= since]

    async def create_order(self, symbol: str, type_: str, side: str, qty: float, price: Any = None,
                           params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        self.orders.append({"symbol": symbol, "type": type_, "side": side, "qty": qty, "params": params})
        if type_ in self.fail_types:
            raise RuntimeError(f"{type_} rejected by fake exchange")
        if type_ == "market" and params.get("reduceOnly"):
            self.positions = [p for p in self.positions if p["symbol"] != symbol]
        elif type_ == "market":
            self.positions.append({"symbol": symbol, "side": "long" if side == "buy" else "short",
                                   "contracts": qty, "entryPrice": self.fill_price or 100.0, "unrealizedPnl": 0.0})
        return {"filled": qty, "average": self.fill_price or 100.0}

    async def cancel_all_orders(self, symbol: str) -> None:
        self.cancelled.append(symbol)

    async def close(self) -> None:
        return None


def live_broker(fx: FakeExchange) -> LiveBroker:
    b = LiveBroker("k", "s", leverage=10)
    asyncio.run(b.exchange.close())  # drop the real ccxt client
    b.exchange = fx
    return b


class FakeMarket:
    def __init__(self, df: Optional[pd.DataFrame] = None) -> None:
        self.df = df if df is not None else candles([100.0] * 5)
        self.calls = 0

    async def closed_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        self.calls += 1
        return self.df

    async def close(self) -> None:
        return None


def candles(closes: List[float], start_ms: int = 0, highs: Optional[List[float]] = None,
            lows: Optional[List[float]] = None) -> pd.DataFrame:
    n = len(closes)
    df = pd.DataFrame({
        "ts_ms": [start_ms + k * 300_000 for k in range(n)],
        "open": closes, "high": highs or [c + 1 for c in closes], "low": lows or [c - 1 for c in closes],
        "close": closes, "volume": [1.0] * n,
    })
    df["timestamp"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    return df


def cfg(**over: Any) -> Dict[str, Any]:
    c = {"symbols": [{"symbol": SYM, "timeframe": "5m", "limit": 150}], "mode": "live", "leverage": 10,
         "risk_pct": 0.01, "max_daily_loss": 0.05, "max_positions": 5, "loop_seconds": 60,
         "max_failed_cycles": 3}
    c.update(over)
    return c


def ledger_row(income: float, kind: str = "REALIZED_PNL", symbol: str = "BTCUSDT", ts: Optional[int] = None) -> Dict:
    return {"amount": income, "info": {"incomeType": kind, "income": str(income), "symbol": symbol,
                                       "time": ts if ts is not None else int(time.time() * 1000)}}


LONG_SIG = {"signal": "long", "entry": 100.0, "sl": 98.0, "tp": 104.0, "rsi": 55.0, "vol_ratio": 1.5, "score": 5}


# ─── Broker: orders ───────────────────────────────────────────────────────────

def test_rejected_stop_loss_closes_the_position_and_raises() -> None:
    fx = FakeExchange()
    fx.fail_types = {"STOP_MARKET"}
    b = live_broker(fx)
    with pytest.raises(OrderError, match="stop-loss rejected.*closed"):
        asyncio.run(b.open_position(SYM, "long", 1.0, 98.0, 104.0, ref_price=100.0))
    stops = [o for o in fx.orders if o["type"] == "STOP_MARKET"]
    assert len(stops) == 2, "the stop is retried once before giving up"
    exit_order = fx.orders[-1]
    assert exit_order["type"] == "market" and exit_order["side"] == "sell" and exit_order["params"]["reduceOnly"]
    assert fx.positions == []


def test_missing_take_profit_keeps_position_with_stop() -> None:
    fx = FakeExchange()
    fx.fail_types = {"TAKE_PROFIT_MARKET"}
    trade = asyncio.run(live_broker(fx).open_position(SYM, "long", 1.0, 98.0, 104.0, ref_price=100.0))
    assert trade["tp_ok"] is False
    assert any(o["type"] == "STOP_MARKET" for o in fx.orders)
    assert len(fx.positions) == 1


def test_fill_beyond_the_stop_is_closed_immediately() -> None:
    fx = FakeExchange()
    fx.fill_price = 97.5                      # slipped below the 98 stop
    with pytest.raises(OrderError, match="beyond the stop"):
        asyncio.run(live_broker(fx).open_position(SYM, "long", 1.0, 98.0, 104.0, ref_price=100.0))
    assert fx.positions == []
    assert not any(o["type"] == "STOP_MARKET" for o in fx.orders)


def test_size_below_exchange_minimum_is_not_sent() -> None:
    fx = FakeExchange()
    with pytest.raises(OrderNotSent):
        asyncio.run(live_broker(fx).open_position(SYM, "long", 0.0004, 98.0, 104.0, ref_price=100.0))
    assert fx.orders == []


def test_emergency_close_of_a_short_buys_back() -> None:
    fx = FakeExchange()
    fx.positions = [{"symbol": SYM, "side": "short", "contracts": 2.0, "unrealizedPnl": 0.0}]
    remaining = asyncio.run(live_broker(fx).close_all())
    assert remaining == []
    assert fx.orders[0]["side"] == "buy" and fx.orders[0]["params"]["reduceOnly"]


def test_entry_carries_a_client_order_id() -> None:
    fx = FakeExchange()
    asyncio.run(live_broker(fx).open_position(SYM, "long", 1.0, 98.0, 104.0, ref_price=100.0, client_id="psbBTC1"))
    assert fx.orders[0]["params"]["clientOrderId"] == "psbBTC1"


def test_income_ledger_ignores_transfers() -> None:
    fx = FakeExchange()
    fx.ledger = [ledger_row(-100.0), ledger_row(-3.0, "COMMISSION"), ledger_row(5000.0, "TRANSFER")]
    assert asyncio.run(live_broker(fx).income_since(0)) == pytest.approx(-103.0)


# ─── Risk ─────────────────────────────────────────────────────────────────────

def test_size_comes_from_the_stop_distance() -> None:
    r = RiskManager(risk_pct=0.01, leverage=10)
    qty = r.position_size(free_margin=10_000, equity=10_000, entry=100.0, sl=98.0)
    assert qty == pytest.approx(50.0)                 # 50 × 2 = 100 USDT = 1% of equity at the stop


def test_size_is_capped_by_free_margin() -> None:
    r = RiskManager(risk_pct=0.01, leverage=10)
    qty = r.position_size(free_margin=100, equity=10_000, entry=100.0, sl=99.9)
    assert qty * 100.0 == pytest.approx(100 * 10 * 0.9)


def test_daily_limit_breach_and_reset() -> None:
    r = RiskManager(max_daily_loss=0.05)
    assert r.update_daily(day_pnl=-300, equity_now=9_700) is False
    assert r.update_daily(day_pnl=-550, equity_now=9_450) is True and r.is_halted()
    r.reset_daily()
    assert not r.is_halted()


# ─── Bot loop ─────────────────────────────────────────────────────────────────

def test_daily_loss_from_exchange_closes_everything_and_halts() -> None:
    fx = FakeExchange()
    fx.ledger = [ledger_row(-400.0)]
    fx.positions = [{"symbol": SYM, "side": "long", "contracts": 1.0, "entryPrice": 100.0, "unrealizedPnl": -150.0}]
    fx.equity = 9_450.0                               # started the day at 10,000: -5.5%
    market = FakeMarket()
    bot = ProScalpingBot(cfg(), broker=live_broker(fx), market=market)
    asyncio.run(bot.run_once())
    assert bot.risk.is_halted()
    assert fx.positions == [], "close-all ran"
    assert market.calls == 0, "no new signals are looked at after the halt"


def test_restart_adopts_positions_already_on_the_exchange() -> None:
    fx = FakeExchange()
    fx.positions = [{"symbol": SYM, "side": "long", "contracts": 1.0, "entryPrice": 100.0, "unrealizedPnl": 0.0}]
    market = FakeMarket()
    bot = ProScalpingBot(cfg(max_positions=1), broker=live_broker(fx), market=market)
    asyncio.run(bot.startup())
    assert bot.open_pos[SYM]["adopted"] is True
    asyncio.run(bot.run_once())
    assert market.calls == 0
    assert not any(o["type"] == "market" for o in fx.orders), "no duplicate entry"


def test_unreadable_account_blocks_new_entries() -> None:
    fx = FakeExchange()
    fx.positions_error = RuntimeError("exchange down")
    market = FakeMarket()
    bot = ProScalpingBot(cfg(), broker=live_broker(fx), market=market)
    asyncio.run(bot.run_once())
    asyncio.run(bot.run_once())
    assert bot.failed_cycles == 2
    assert market.calls == 0 and fx.orders == []


def test_closed_trade_records_exchange_pnl_and_cancels_orphans() -> None:
    fx = FakeExchange()
    fx.ledger = [ledger_row(-50.0), ledger_row(-2.0, "COMMISSION")]
    bot = ProScalpingBot(cfg(), broker=live_broker(fx), market=FakeMarket())
    bot.open_pos[SYM] = {"symbol": SYM, "side": "long", "opened_at": time.time() - 600}
    asyncio.run(bot._sync())
    assert SYM not in bot.open_pos
    assert fx.cancelled == [SYM]
    assert bot.risk.stats()["consec_losses"] == 1
    assert bot.risk.stats()["total_pnl"] == pytest.approx(-52.0)


def test_two_order_errors_halt_new_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    fx = FakeExchange()
    fx.fail_types = {"STOP_MARKET"}
    syms = [{"symbol": s, "timeframe": "5m"} for s in ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT")]
    bot = ProScalpingBot(cfg(symbols=syms), broker=live_broker(fx), market=FakeMarket())
    monkeypatch.setattr(bot.strategy, "generate", lambda df: dict(LONG_SIG))
    asyncio.run(bot.run_once())
    assert bot.risk.is_halted() and "order errors" in bot.risk.halt_reason
    entries = [o for o in fx.orders if o["type"] == "market" and not o["params"].get("reduceOnly")]
    assert len(entries) == 2, "the third symbol is skipped after the halt"
    assert fx.positions == []


def test_live_mode_sizes_from_stop_and_registers_trade(monkeypatch: pytest.MonkeyPatch) -> None:
    fx = FakeExchange()
    bot = ProScalpingBot(cfg(), broker=live_broker(fx), market=FakeMarket())
    monkeypatch.setattr(bot.strategy, "generate", lambda df: dict(LONG_SIG))
    asyncio.run(bot.run_once())
    entry = fx.orders[0]
    assert entry["type"] == "market" and entry["qty"] == pytest.approx(50.0)
    assert entry["params"]["clientOrderId"].startswith("psbBTCUSDT")
    assert SYM in bot.open_pos


# ─── Market data, config, paper ───────────────────────────────────────────────

def test_forming_candle_is_dropped() -> None:
    now = int(time.time() * 1000)
    bar = 300_000
    last_open = now - now % bar                       # the candle that is still forming
    rows = [[last_open - k * bar, 1, 2, 0.5, 1.5, 10] for k in range(3, -1, -1)]

    class Ex:
        async def fetch_ohlcv(self, *a: Any, **k: Any) -> list:
            return rows

        def parse_timeframe(self, tf: str) -> int:
            return 300

        def milliseconds(self) -> int:
            return now

    md = MarketData.__new__(MarketData)
    md.ex = Ex()
    df = asyncio.run(md.closed_ohlcv(SYM, "5m", 3))
    assert len(df) == 3 and int(df["ts_ms"].iloc[-1]) == last_open - bar


def test_config_defaults_to_paper_and_checks_ranges(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "c.yaml"
    p.write_text("symbols:\n  - {symbol: 'BTC/USDT:USDT'}\n", encoding="utf-8")
    for var in ("TRADING_MODE", "RISK_PCT", "LEVERAGE", "BINANCE_API_KEY", "BINANCE_API_SECRET"):
        monkeypatch.delenv(var, raising=False)
    assert load_config(str(p))["mode"] == "paper"
    monkeypatch.setenv("RISK_PCT", "1")
    with pytest.raises(ConfigError, match="risk_pct"):
        load_config(str(p))
    monkeypatch.setenv("RISK_PCT", "0.01")
    monkeypatch.setenv("LEVERAGE", "125")
    with pytest.raises(ConfigError, match="leverage"):
        load_config(str(p))


def test_live_mode_without_keys_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    with pytest.raises(ConfigError, match="needs BINANCE_API_KEY"):
        ProScalpingBot(cfg(mode="live"), market=FakeMarket())


def test_hedge_mode_account_is_refused() -> None:
    fx = FakeExchange()
    fx.hedged = True
    with pytest.raises(OrderError, match="hedge mode"):
        asyncio.run(live_broker(fx).check_account())


def test_paper_stop_comes_first_when_a_candle_hits_both() -> None:
    now = int(time.time() * 1000)
    bar_open = now - now % 300_000
    market = FakeMarket(candles([100.0], start_ms=bar_open, highs=[105.0], lows=[97.0]))
    pb = PaperBroker(market, balance=10_000, fee_pct=0.0)
    asyncio.run(pb.open_position(SYM, "long", 10.0, 98.0, 104.0, ref_price=100.0, timeframe="5m"))
    assert asyncio.run(pb.get_positions()) == []
    assert asyncio.run(pb.income_since(0, SYM)) == pytest.approx(-20.0)


def test_utc_midnight() -> None:
    from datetime import datetime, timezone
    t = datetime(2026, 11, 7, 15, 30, tzinfo=timezone.utc)
    assert utc_midnight_ms(t) == int(datetime(2026, 11, 7, tzinfo=timezone.utc).timestamp() * 1000)
