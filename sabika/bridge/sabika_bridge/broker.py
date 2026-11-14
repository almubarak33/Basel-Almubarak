"""Broker interface used by the engine.

Real adapter: broker_mt5.Mt5Broker (Windows, MetaTrader5 package).
Test adapter: broker_sim.SimBroker.
"""
from dataclasses import dataclass


@dataclass
class SymbolSpec:
    name: str
    digits: int
    point: float
    contract_size: float
    volume_min: float
    volume_step: float
    volume_max: float
    stops_level_points: int = 0


@dataclass
class Tick:
    bid: float
    ask: float
    time: float          # broker-server epoch seconds of the last quote


@dataclass
class Account:
    equity: float
    balance: float
    currency: str
    is_demo: bool
    trade_allowed: bool = True


@dataclass
class Position:
    ticket: int
    symbol: str
    side: str            # "buy" | "sell"
    volume: float
    price_open: float
    sl: float
    tp: float
    profit: float
    magic: int
    comment: str = ""


@dataclass
class OrderResult:
    ok: bool
    ticket: int = 0
    price: float = 0.0
    volume: float = 0.0
    retcode: int = 0
    message: str = ""


class Broker:
    """All money values are in the account currency."""

    def account(self) -> Account:
        raise NotImplementedError

    def symbol(self, name: str):
        """SymbolSpec, or None if the symbol does not exist."""
        raise NotImplementedError

    def tick(self, name: str):
        """Latest Tick, or None if there is no quote."""
        raise NotImplementedError

    def loss_at_stop(self, name: str, side: str, volume: float, entry: float, stop: float):
        """Money lost (positive number) if a position of `volume` opened at `entry` is closed at `stop`."""
        raise NotImplementedError

    def market_order(self, name: str, side: str, volume: float, sl: float, tp: float, magic: int, comment: str) -> OrderResult:
        raise NotImplementedError

    def positions(self, magic: int):
        """Open positions that carry this magic number."""
        raise NotImplementedError

    def close(self, position: Position) -> OrderResult:
        raise NotImplementedError

    def server_day(self) -> str:
        """Current trading day in broker-server time, as YYYY-MM-DD."""
        raise NotImplementedError
