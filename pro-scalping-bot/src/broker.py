"""
broker.py – Binance USDT-M Futures live broker.

Safety rules (see README.md):
- Quantities and prices go through the exchange's precision and minimum rules.
- A position is never left without a stop: if the stop-loss order is rejected
  twice, the position is closed at market and OrderError is raised.
- The day's PnL is read from the exchange income ledger, so the daily-loss
  limit survives restarts.
- One-way position mode only (hedge mode is refused at startup).
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import ccxt.async_support as ccxt

log = logging.getLogger("broker")

# Ledger income types that change the account's trading PnL (deposits and transfers excluded).
INCOME_TYPES = {"REALIZED_PNL", "COMMISSION", "FUNDING_FEE"}


class OrderError(RuntimeError):
    """An order could not be placed safely. The message says what state the account is in."""


class OrderNotSent(OrderError):
    """Nothing was sent to the exchange (e.g. the size is below the exchange minimum)."""


class LiveBroker:
    mode = "live"

    def __init__(self, api_key: str, api_secret: str, leverage: int = 10):
        self.leverage = leverage
        self.exchange = ccxt.binanceusdm({
            "apiKey":          api_key,
            "secret":          api_secret,
            "enableRateLimit": True,
            "options":         {"defaultType": "future"},
        })
        self._markets_loaded = False

    # ── Setup ─────────────────────────────────────────────────────────────────

    async def ensure_markets(self) -> None:
        if not self._markets_loaded:
            await self.exchange.load_markets()
            self._markets_loaded = True

    async def check_account(self) -> None:
        """Refuse to trade in hedge mode: every order here assumes one-way mode."""
        await self.ensure_markets()
        try:
            mode = await self.exchange.fetch_position_mode()
        except Exception as e:  # not fatal: Binance defaults to one-way mode
            log.warning(f"Could not read the position mode ({e}); assuming one-way mode.")
            return
        if mode.get("hedged"):
            raise OrderError("The account is in hedge mode; switch Binance Futures to one-way mode first.")

    async def prepare_symbol(self, symbol: str) -> None:
        """Set leverage and isolated margin before trading."""
        try:
            await self.exchange.set_leverage(self.leverage, symbol)
        except Exception as e:
            log.warning(f"set_leverage {symbol}: {e}")
        try:
            await self.exchange.set_margin_mode("isolated", symbol)
        except Exception as e:
            log.debug(f"set_margin_mode {symbol}: {e}")  # usually "no need to change"

    # ── Account ───────────────────────────────────────────────────────────────

    async def get_balance(self) -> float:
        """Free USDT available as margin."""
        data = await self.exchange.fetch_balance()
        return float(data["USDT"]["free"])

    async def get_equity(self) -> float:
        """Wallet balance plus unrealized PnL (Binance 'margin balance')."""
        data = await self.exchange.fetch_balance()
        info = data.get("info") or {}
        if info.get("totalMarginBalance") is not None:
            return float(info["totalMarginBalance"])
        upnl = sum(float(p.get("unrealizedPnl") or 0) for p in await self.get_positions())
        return float(data["USDT"]["total"]) + upnl

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Open positions. ccxt reports 'contracts' as a positive size and the direction in 'side'."""
        positions = await self.exchange.fetch_positions()
        return [p for p in positions if abs(float(p.get("contracts") or 0)) > 0]

    async def income_since(self, since_ms: int, symbol: Optional[str] = None) -> float:
        """Realized PnL + commissions + funding since `since_ms` (UTC, ms), optionally for one symbol."""
        await self.ensure_markets()
        market_id = self.exchange.market(symbol)["id"] if symbol else None
        entries = await self.exchange.fetch_ledger("USDT", since_ms, 1000)
        if len(entries) >= 1000:
            log.warning("Income ledger returned 1000 rows; older rows of the day may be missing.")
        total = 0.0
        for e in entries:
            info = e.get("info") or {}
            if info.get("incomeType") not in INCOME_TYPES:
                continue
            if market_id and info.get("symbol") != market_id:
                continue
            total += float(info.get("income") if info.get("income") is not None else e.get("amount") or 0)
        return total

    # ── Precision ─────────────────────────────────────────────────────────────

    def _amount(self, symbol: str, qty: float) -> float:
        try:
            return float(self.exchange.amount_to_precision(symbol, qty))
        except Exception:  # ccxt raises when the amount rounds below the minimum
            return 0.0

    def _price(self, symbol: str, price: float) -> float:
        return float(self.exchange.price_to_precision(symbol, price))

    def _size_problem(self, symbol: str, qty: float, price: float) -> Optional[str]:
        limits = self.exchange.market(symbol).get("limits") or {}
        amin = (limits.get("amount") or {}).get("min")
        cmin = (limits.get("cost") or {}).get("min")
        if qty <= 0:
            return "the quantity rounds to zero at the exchange's step size"
        if amin and qty < amin:
            return f"quantity {qty} is below the exchange minimum {amin}"
        if cmin and price > 0 and qty * price < cmin:
            return f"order value {qty * price:.2f} USDT is below the exchange minimum {cmin}"
        return None

    # ── Orders ────────────────────────────────────────────────────────────────

    async def _place_with_retry(self, label: str, *args: Any, tries: int = 2) -> None:
        last: Optional[Exception] = None
        for k in range(tries):
            try:
                await self.exchange.create_order(*args)
                return
            except Exception as e:
                last = e
                log.error(f"{label} attempt {k + 1}/{tries} failed: {e}")
                if k + 1 < tries:
                    await asyncio.sleep(1.0)
        raise last  # type: ignore[misc]

    async def open_position(
        self,
        symbol:    str,
        side:      str,              # "long" | "short"
        qty:       float,
        sl:        float,
        tp:        float,
        ref_price: float,
        client_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Market entry, then a reduce-only stop-loss and take-profit.
        Raises OrderError (with the position closed) if the stop cannot be placed."""
        await self.ensure_markets()
        await self.prepare_symbol(symbol)

        order_side = "buy" if side == "long" else "sell"
        exit_side = "sell" if side == "long" else "buy"
        qty = self._amount(symbol, qty)
        sl_p = self._price(symbol, sl)
        tp_p = self._price(symbol, tp)
        problem = self._size_problem(symbol, qty, ref_price)
        if problem:
            raise OrderNotSent(f"{symbol}: not sent — {problem}")

        params: Dict[str, Any] = {"clientOrderId": client_id} if client_id else {}
        entry_order = await self.exchange.create_order(symbol, "market", order_side, qty, None, params)
        filled = float(entry_order.get("filled") or 0) or qty
        entry_price = float(entry_order.get("average") or entry_order.get("price") or 0) or ref_price

        # A fill already beyond the stop would trigger (or be rejected) at once: get out now.
        if (side == "long" and entry_price <= sl_p) or (side == "short" and entry_price >= sl_p):
            closed = await self._flatten(symbol, side, filled)
            raise OrderError(f"{symbol}: filled at {entry_price} beyond the stop {sl_p}; "
                             f"position {'closed' if closed else 'NOT CLOSED — check Binance now'}")

        try:
            await self._place_with_retry(f"SL {symbol}", symbol, "STOP_MARKET", exit_side, filled, None,
                                         {"stopPrice": sl_p, "reduceOnly": True})
        except Exception as e:
            log.critical(f"[SL FAILED] {symbol}: {e} — closing the position at market")
            closed = await self._flatten(symbol, side, filled)
            raise OrderError(f"{symbol}: stop-loss rejected ({e}); position "
                             f"{'closed' if closed else 'NOT CLOSED — check Binance now'}") from e

        tp_ok = True
        try:
            await self._place_with_retry(f"TP {symbol}", symbol, "TAKE_PROFIT_MARKET", exit_side, filled, None,
                                         {"stopPrice": tp_p, "reduceOnly": True})
        except Exception as e:
            tp_ok = False  # the stop protects the position; the target is missing
            log.error(f"[TP MISSING] {symbol}: {e} — position open with stop only")

        log.info(f"[OPEN]  {symbol} {side.upper():5s} | entry={entry_price}  sl={sl_p}  tp={tp_p}  qty={filled}")
        return {"symbol": symbol, "side": side, "entry": entry_price, "qty": filled,
                "sl": sl_p, "tp": tp_p, "tp_ok": tp_ok}

    async def _flatten(self, symbol: str, side: str, qty: float) -> bool:
        """Close `qty` of a position at market and cancel its orders. True if no position is left."""
        exit_side = "sell" if side == "long" else "buy"
        try:
            await self.exchange.create_order(symbol, "market", exit_side, qty, None, {"reduceOnly": True})
        except Exception as e:
            log.critical(f"[FLATTEN FAILED] {symbol}: {e}")
        await self.cancel_orders(symbol)
        try:
            left = [p for p in await self.get_positions() if p.get("symbol") == symbol]
        except Exception as e:
            log.critical(f"[FLATTEN UNVERIFIED] {symbol}: {e}")
            return False
        return not left

    async def cancel_orders(self, symbol: str) -> None:
        """Cancel every open order on a symbol (orphan stop or target after a close)."""
        try:
            await self.exchange.cancel_all_orders(symbol)
        except Exception as e:
            log.warning(f"cancel_all_orders {symbol}: {e}")

    async def close_position(self, symbol: str, side: str, contracts: float) -> bool:
        """Emergency close one position. `side` is the position side ('long'/'short')."""
        ok = await self._flatten(symbol, side, abs(contracts))
        log.info(f"[CLOSE] {symbol} emergency close {'done' if ok else 'FAILED'}")
        return ok

    async def close_all(self) -> List[str]:
        """Emergency close every open position. Returns the symbols still open afterwards."""
        for p in await self.get_positions():
            await self.close_position(p["symbol"], p.get("side") or "long", float(p.get("contracts") or 0))
        return [p["symbol"] for p in await self.get_positions()]

    async def close(self) -> None:
        await self.exchange.close()
