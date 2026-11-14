"""Run the bridge:  python -m sabika_bridge --config config.toml   (add --sim to run without MetaTrader 5)."""
import argparse
import logging
import time

from .config import load
from .engine import Engine
from .server import BridgeServer
from .store import Store


def main():
    ap = argparse.ArgumentParser(prog="sabika_bridge")
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--sim", action="store_true", help="use the simulated broker instead of MetaTrader 5 (wiring tests only)")
    ap.add_argument("--reset-total-lock", action="store_true", help="operator action: clear the total-loss lock and exit")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler("sabika_bridge.log", encoding="utf-8")])
    cfg = load(args.config)
    if not cfg.symbols:
        raise SystemExit("config has no [symbols] mapping")
    if args.sim:
        from .broker_sim import SimBroker
        broker = SimBroker()
        for name in set(cfg.symbols.values()):
            broker.add_symbol(name, 3900.00, 3900.30)
    else:
        from .broker_mt5 import Mt5Broker
        broker = Mt5Broker(clock_symbol=next(iter(cfg.symbols.values())))
    engine = Engine(cfg, broker, Store(cfg.db_path))
    if args.reset_total_lock:
        engine.reset_total_lock()
        print("total-loss lock cleared; new reference equity recorded")
        return
    acct = broker.account()
    logging.getLogger("sabika.bridge").info("account: %s, equity %.2f %s", "DEMO" if acct.is_demo else "REAL", acct.equity, acct.currency)
    server = BridgeServer(cfg, engine)
    server.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
