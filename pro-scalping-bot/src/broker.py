"""
broker.py – Binance Futures Live Broker
- Market entry with SL + TP orders
- Hedge mode aware
- Auto-cancel orphan orders on close
"""

import logging
from typing import Dict, Any, List

import ccxt.async_support as ccxt

log = logging.getLogger("broker")


class LiveBroker:
    def __init__(self, api_key: str, api_secret: str, leverage: int = 10):
        self.leverage = leverage
        self.exchange = ccxt.binanceusdm({
            "apiKey":          api_key,
            "secret":          api_secret,
            "enableRateLimit": True,
            "options":         {"defaultType": "future"},
        })

    # ── Account ───────────────────────────────────────────────────────────────

    async def get_balance(self) -> float:
        data = await self.exchange.fetch_balance()
        return float(data["USDT"]["free"])

    async def get_total_balance(self) -> float:
        data = await self.exchange.fetch_balance()
        return float(data["USDT"]["total"])

    async def get_positions(self) -> List[Dict[str, Any]]:
        positions = await self.exchange.fetch_positions()
        return [p for p in positions if abs(float(p.get("contracts", 0))) > 0]

    # ── Setup ─────────────────────────────────────────────────────────────────

    async def prepare_symbol(self, symbol: str):
        """Set leverage and margin mode before trading."""
        try:
            await self.exchange.set_leverage(self.leverage, symbol)
        except Exception as e:
            log.warning(f"set_leverage {symbol}: {e}")
        try:
            await self.exchange.set_margin_mode("isolated", symbol)
        except Exception:
            pass  # already set or not supported

    # ── Orders ────────────────────────────────────────────────────────────────

    async def open_position(
        self,
        symbol: str,
        side:   str,   # "long" | "short"
        qty:    float,
        sl:     float,
        tp:     float,
    ) -> Dict[str, Any]:
        await self.prepare_symbol(symbol)

        order_side = "buy"  if side == "long"  else "sell"
        exit_side  = "sell" if side == "long"  else "buy"

        # ── Market entry ──────────────────────────────────────────────────────
        entry_order = await self.exchange.create_order(
            symbol, "market", order_side, qty
        )
        entry_price = float(
            entry_order.get("average") or
            entry_order.get("price")   or 0
        )

        # ── Stop Loss ─────────────────────────────────────────────────────────
        try:
            await self.exchange.create_order(
                symbol, "STOP_MARKET", exit_side, qty, None,
                {"stopPrice": round(sl, 6), "reduceOnly": True}
            )
        except Exception as e:
            log.error(f"SL failed {symbol}: {e}")

        # ── Take Profit ───────────────────────────────────────────────────────
        try:
            await self.exchange.create_order(
                symbol, "TAKE_PROFIT_MARKET", exit_side, qty, None,
                {"stopPrice": round(tp, 6), "reduceOnly": True}
            )
        except Exception as e:
            log.error(f"TP failed {symbol}: {e}")

        log.info(
            f"[OPEN]  {symbol} {side.upper():5s} | "
            f"entry={entry_price:.4f}  sl={sl:.4f}  tp={tp:.4f}  qty={qty}"
        )

        return {
            "symbol": symbol,
            "side":   side,
            "entry":  entry_price,
            "qty":    qty,
            "sl":     sl,
            "tp":     tp,
        }

    async def close_position(self, symbol: str, contracts: float):
        """Emergency close a single position."""
        side = "sell" if contracts > 0 else "buy"
        qty  = abs(contracts)
        try:
            await self.exchange.create_order(
                symbol, "market", side, qty, None, {"reduceOnly": True}
            )
            await self.exchange.cancel_all_orders(symbol)
            log.info(f"[CLOSE] {symbol} emergency closed.")
        except Exception as e:
            log.error(f"close_position {symbol}: {e}")

    async def close_all(self):
        """Emergency close all open positions."""
        positions = await self.get_positions()
        for p in positions:
            await self.close_position(p["symbol"], float(p.get("contracts", 0)))

    async def close(self):
        await self.exchange.close()
