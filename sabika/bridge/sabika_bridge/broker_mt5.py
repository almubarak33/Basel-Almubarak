"""MetaTrader 5 adapter (Windows only; needs `pip install MetaTrader5` and a running, logged-in terminal).

NOT yet exercised against a live terminal: written from the official package documentation and to be verified on the
demo account before anything else relies on it.
"""
from datetime import datetime, timezone

from .broker import Account, Broker, OrderResult, Position, SymbolSpec, Tick


class Mt5Broker(Broker):
    def __init__(self, clock_symbol, terminal_path=None, deviation_points=50):
        import MetaTrader5 as mt5                      # imported here so the rest of the package runs without it
        self.mt5 = mt5
        self.clock_symbol = clock_symbol
        self.deviation = int(deviation_points)
        ok = mt5.initialize(path=terminal_path) if terminal_path else mt5.initialize()
        if not ok:
            raise RuntimeError("MetaTrader5.initialize failed: %s" % (mt5.last_error(),))

    def account(self):
        a = self.mt5.account_info()
        if a is None:
            raise RuntimeError("account_info failed: %s" % (self.mt5.last_error(),))
        return Account(a.equity, a.balance, a.currency, a.trade_mode == self.mt5.ACCOUNT_TRADE_MODE_DEMO,
                       bool(a.trade_allowed and a.trade_expert))

    def _info(self, name):
        info = self.mt5.symbol_info(name)
        if info is not None and not info.visible:
            self.mt5.symbol_select(name, True)
            info = self.mt5.symbol_info(name)
        return info

    def symbol(self, name):
        i = self._info(name)
        if i is None:
            return None
        return SymbolSpec(name, i.digits, i.point, i.trade_contract_size, i.volume_min, i.volume_step, i.volume_max, i.trade_stops_level)

    def tick(self, name):
        t = self.mt5.symbol_info_tick(name)
        return None if t is None else Tick(t.bid, t.ask, float(t.time))

    def loss_at_stop(self, name, side, volume, entry, stop):
        kind = self.mt5.ORDER_TYPE_BUY if side == "buy" else self.mt5.ORDER_TYPE_SELL
        p = self.mt5.order_calc_profit(kind, name, float(volume), float(entry), float(stop))
        return None if p is None else max(0.0, -p)

    def _filling(self, info):
        if info.filling_mode & 1:
            return self.mt5.ORDER_FILLING_FOK
        if info.filling_mode & 2:
            return self.mt5.ORDER_FILLING_IOC
        return self.mt5.ORDER_FILLING_RETURN

    def _send(self, request):
        res = self.mt5.order_send(request)
        if res is None:
            return OrderResult(False, message="order_send failed: %s" % (self.mt5.last_error(),))
        ok = res.retcode in (self.mt5.TRADE_RETCODE_DONE, self.mt5.TRADE_RETCODE_DONE_PARTIAL)
        return OrderResult(ok, int(res.order), float(res.price), float(res.volume), int(res.retcode), str(res.comment))

    def market_order(self, name, side, volume, sl, tp, magic, comment):
        info, t = self._info(name), self.mt5.symbol_info_tick(name)
        if info is None or t is None:
            return OrderResult(False, message="no symbol or quote")
        buy = side == "buy"
        return self._send({
            "action": self.mt5.TRADE_ACTION_DEAL, "symbol": name, "volume": float(volume),
            "type": self.mt5.ORDER_TYPE_BUY if buy else self.mt5.ORDER_TYPE_SELL,
            "price": t.ask if buy else t.bid, "sl": round(float(sl), info.digits), "tp": round(float(tp), info.digits),
            "deviation": self.deviation, "magic": int(magic), "comment": comment[:31],
            "type_time": self.mt5.ORDER_TIME_GTC, "type_filling": self._filling(info)})

    def positions(self, magic):
        out = []
        for p in self.mt5.positions_get() or ():
            if p.magic == magic:
                side = "buy" if p.type == self.mt5.POSITION_TYPE_BUY else "sell"
                out.append(Position(int(p.ticket), p.symbol, side, float(p.volume), float(p.price_open), float(p.sl), float(p.tp),
                                    float(p.profit), int(p.magic), str(p.comment)))
        return out

    def close(self, position):
        info, t = self._info(position.symbol), self.mt5.symbol_info_tick(position.symbol)
        if info is None or t is None:
            return OrderResult(False, message="no symbol or quote")
        buy = position.side == "buy"
        return self._send({
            "action": self.mt5.TRADE_ACTION_DEAL, "symbol": position.symbol, "volume": float(position.volume),
            "type": self.mt5.ORDER_TYPE_SELL if buy else self.mt5.ORDER_TYPE_BUY, "position": int(position.ticket),
            "price": t.bid if buy else t.ask, "deviation": self.deviation, "magic": int(position.magic),
            "comment": "sabika close", "type_time": self.mt5.ORDER_TIME_GTC, "type_filling": self._filling(info)})

    def server_day(self):
        t = self.mt5.symbol_info_tick(self.clock_symbol)
        if t is None:
            raise RuntimeError("no quote for %s" % self.clock_symbol)
        return datetime.fromtimestamp(t.time, timezone.utc).date().isoformat()   # tick time is broker-server time
