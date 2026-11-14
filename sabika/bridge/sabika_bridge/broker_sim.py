"""Simulated broker for tests and dry runs. Prices are set by the caller; fills are immediate."""
from .broker import Account, Broker, OrderResult, Position, SymbolSpec, Tick


class SimBroker(Broker):
    def __init__(self, equity=10000.0, is_demo=True, day="2026-11-16"):
        self.balance = equity
        self.is_demo = is_demo
        self.day = day
        self.specs = {}
        self.ticks = {}
        self._positions = []
        self._next_ticket = 1000
        self.fail_next_order = None      # set to a message to make the next market order fail
        self.drop_sl_on_fill = False     # simulate a broker that ignores the stop on entry

    # ---- test helpers
    def add_symbol(self, name, bid, ask, contract=100.0, vmin=0.01, vstep=0.01, vmax=50.0, digits=2, stops_level=0):
        self.specs[name] = SymbolSpec(name, digits, 10 ** -digits, contract, vmin, vstep, vmax, stops_level)
        self.ticks[name] = Tick(bid, ask, 0.0)

    def set_price(self, name, bid, ask):
        """Move the quote and apply stop-loss / take-profit to open positions."""
        self.ticks[name] = Tick(bid, ask, self.ticks[name].time + 1)
        for p in list(self._positions):
            if p.symbol != name:
                continue
            px = bid if p.side == "buy" else ask
            hit_sl = p.sl > 0 and (px <= p.sl if p.side == "buy" else px >= p.sl)
            hit_tp = p.tp > 0 and (px >= p.tp if p.side == "buy" else px <= p.tp)
            if hit_sl or hit_tp:
                self._settle(p, p.sl if hit_sl else p.tp)

    def _pl(self, p, price):
        sign = 1 if p.side == "buy" else -1
        return sign * (price - p.price_open) * self.specs[p.symbol].contract_size * p.volume

    def _settle(self, p, price):
        self.balance += self._pl(p, price)
        self._positions.remove(p)

    # ---- Broker interface
    def account(self):
        floating = 0.0
        for p in self._positions:
            t = self.ticks[p.symbol]
            floating += self._pl(p, t.bid if p.side == "buy" else t.ask)
        return Account(self.balance + floating, self.balance, "USD", self.is_demo)

    def symbol(self, name):
        return self.specs.get(name)

    def tick(self, name):
        return self.ticks.get(name)

    def loss_at_stop(self, name, side, volume, entry, stop):
        spec = self.specs.get(name)
        if spec is None:
            return None
        sign = 1 if side == "buy" else -1
        return max(0.0, sign * (entry - stop) * spec.contract_size * volume)

    def market_order(self, name, side, volume, sl, tp, magic, comment):
        if self.fail_next_order:
            msg, self.fail_next_order = self.fail_next_order, None
            return OrderResult(False, retcode=10006, message=msg)
        t = self.ticks[name]
        price = t.ask if side == "buy" else t.bid
        ticket = self._next_ticket
        self._next_ticket += 1
        self._positions.append(Position(ticket, name, side, volume, price, 0.0 if self.drop_sl_on_fill else sl, tp, 0.0, magic, comment))
        return OrderResult(True, ticket, price, volume, 10009, "done")

    def positions(self, magic):
        return [p for p in self._positions if p.magic == magic]

    def close(self, position):
        t = self.ticks[position.symbol]
        price = t.bid if position.side == "buy" else t.ask
        for p in self._positions:
            if p.ticket == position.ticket:
                self._settle(p, price)
                return OrderResult(True, position.ticket, price, position.volume, 10009, "closed")
        return OrderResult(False, message="position not found")

    def server_day(self):
        return self.day
