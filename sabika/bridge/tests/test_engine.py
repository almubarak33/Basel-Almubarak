import os
import tempfile
import unittest

from sabika_bridge.broker_sim import SimBroker
from sabika_bridge.config import Config, Risk, Source
from sabika_bridge.engine import Engine
from sabika_bridge.store import Store

SYM = "CAPITALCOM:XAUUSD"
T0 = 1_794_800_000.0          # fixed "now" in epoch seconds


def make(mode="demo", equity=10000.0, is_demo=True, db=None, **risk):
    cfg = Config(mode=mode, secret="x" * 16, risk=Risk(**risk), symbols={SYM: "GOLD"},
                 sources={"GOLDV2": Source(enabled=True), "OFF": Source(enabled=False)})
    broker = SimBroker(equity=equity, is_demo=is_demo)
    broker.add_symbol("GOLD", 3900.00, 3900.30)
    clock = [T0]
    engine = Engine(cfg, broker, Store(db or ":memory:"), clock=lambda: clock[0])
    return engine, broker, clock


def entry(i=1, side="buy", price=3900.30, risk=20.0, t=T0, **over):
    sign = 1 if side == "buy" else -1
    m = {"v": 1, "type": "entry", "src": "GOLDV2", "sym": SYM, "tf": 5, "side": side, "id": "GOLDV2-5-%d" % i,
         "t": int(t * 1000), "entry": price, "sl": price - sign * risk, "tp1": price + sign * risk,
         "tp2": price + sign * 1.5 * risk, "tp3": price + sign * 2 * risk, "expire": int((t + 7200) * 1000)}
    m.update(over)
    return m


class Sizing(unittest.TestCase):
    def test_executes_with_risk_based_size_and_stop(self):
        e, b, _ = make()
        d = e.handle(entry())
        self.assertEqual(d["status"], "executed", d)
        # 0.5% of 10,000 = 50; stop 20.00 away; 100 oz per lot -> 2000 per lot -> 0.025 -> floored to 0.02
        self.assertEqual(d["detail"]["lots"], 0.02)
        self.assertLessEqual(d["detail"]["planned_loss"], 50.0)
        pos = b.positions(e.cfg.magic)[0]
        self.assertEqual((pos.sl, pos.tp, pos.volume), (3880.30, 3920.30, 0.02))

    def test_never_rounds_up_to_minimum_lot(self):
        e, b, _ = make(equity=300.0)                     # 0.5% = 1.50, min lot would lose 20.00
        d = e.handle(entry())
        self.assertEqual((d["status"], d["reason"]), ("rejected", "below_min_lot"))
        self.assertEqual(b.positions(e.cfg.magic), [])

    def test_notional_cap_binds_on_tight_stop(self):
        e, _, _ = make(max_notional_x_equity=1.0)
        d = e.handle(entry(risk=5.0))                    # risk allows 0.10 lots, 1x equity allows 0.02
        self.assertEqual(d["status"], "executed", d)
        self.assertEqual((d["detail"]["lots"], d["detail"]["binding"]), (0.02, "max_notional"))

    def test_sell_side(self):
        e, b, _ = make()
        d = e.handle(entry(side="sell", price=3900.00))
        self.assertEqual(d["status"], "executed", d)
        pos = b.positions(e.cfg.magic)[0]
        self.assertEqual((pos.side, pos.sl, pos.tp), ("sell", 3920.00, 3880.00))


class Gates(unittest.TestCase):
    def reason(self, e, m):
        d = e.handle(m)
        return d["status"], d["reason"]

    def test_duplicate_is_ignored(self):
        e, b, _ = make()
        e.handle(entry())
        self.assertEqual(e.handle(entry())["status"], "duplicate")
        self.assertEqual(len(b.positions(e.cfg.magic)), 1)

    def test_stale_signal(self):
        e, _, _ = make()
        self.assertEqual(self.reason(e, entry(t=T0 - 60)), ("rejected", "stale"))

    def test_price_far_from_model(self):
        e, b, _ = make()
        b.set_price("GOLD", 3908.00, 3908.30)            # 8.00 above the model entry, risk 20 -> 40% > 25%
        self.assertEqual(self.reason(e, entry()), ("rejected", "price_far_from_model"))

    def test_spread_too_wide(self):
        e, b, _ = make()
        b.set_price("GOLD", 3897.30, 3900.30)            # spread 3.00 on a 20.00 stop = 15% > 12%
        self.assertEqual(self.reason(e, entry()), ("rejected", "spread_too_wide"))

    def test_disabled_source_unknown_symbol_and_bad_message(self):
        e, _, _ = make()
        self.assertEqual(self.reason(e, entry(src="OFF", id="a")), ("rejected", "source_disabled"))
        self.assertEqual(self.reason(e, entry(sym="OANDA:EURUSD", id="b")), ("rejected", "unknown_symbol"))
        self.assertEqual(self.reason(e, entry(sl=4000.0, id="c")), ("rejected", "stop_on_wrong_side"))
        self.assertEqual(self.reason(e, {"hello": 1}), ("rejected", "bad_version"))

    def test_real_account_refused_unless_live_and_armed(self):
        e, b, _ = make(mode="demo", is_demo=False)
        self.assertEqual(self.reason(e, entry()), ("rejected", "real_account_but_mode_is_demo"))
        e2, _, _ = make(mode="live", is_demo=False)
        self.assertEqual(self.reason(e2, entry()), ("rejected", "live_not_armed"))
        self.assertEqual(b.positions(e.cfg.magic), [])

    def test_monitor_mode_sends_nothing(self):
        e, b, _ = make(mode="monitor")
        d = e.handle(entry())
        self.assertEqual(d["status"], "monitor_only")
        self.assertEqual(d["detail"]["lots"], 0.02)
        self.assertEqual(b.positions(e.cfg.magic), [])

    def test_position_and_daily_trade_caps(self):
        e, _, _ = make(max_open_positions=1)
        e.handle(entry(1))
        self.assertEqual(self.reason(e, entry(2)), ("rejected", "max_open_positions"))
        e2, b2, _ = make(max_trades_per_day=2, max_open_positions=5)
        for i in (1, 2):
            self.assertEqual(e2.handle(entry(i))["status"], "executed")
        self.assertEqual(self.reason(e2, entry(3)), ("rejected", "max_trades_per_day"))

    def test_order_failure_and_missing_stop(self):
        e, b, _ = make()
        b.fail_next_order = "no money"
        self.assertEqual(e.handle(entry(1))["status"], "order_failed")
        b.drop_sl_on_fill = True
        d = e.handle(entry(2))
        self.assertEqual(d["status"], "closed_no_stop")
        self.assertEqual(b.positions(e.cfg.magic), [])


class Protection(unittest.TestCase):
    def test_stop_loss_is_enforced_by_the_broker_and_reconciled(self):
        e, b, _ = make()
        e.handle(entry())
        b.set_price("GOLD", 3880.00, 3880.30)            # bid through the stop at 3880.30
        e.manage()
        self.assertEqual(b.positions(e.cfg.magic), [])
        self.assertEqual(e.store.open_trades(), [])
        self.assertAlmostEqual(b.account().equity, 10000 - 0.02 * 100 * 20.0, places=2)

    def test_time_exit(self):
        e, b, clock = make()
        e.handle(entry())
        clock[0] = T0 + 7201
        e.manage()
        self.assertEqual(b.positions(e.cfg.magic), [])
        rows = e.store._all("SELECT close_reason FROM trades")
        self.assertEqual(rows[0]["close_reason"], "time_exit")

    def test_daily_loss_lock_flattens_and_survives_restart(self):
        path = os.path.join(tempfile.mkdtemp(), "j.sqlite")
        e, b, clock = make(db=path, max_daily_loss_pct=2.0, max_notional_x_equity=5.0, risk_pct=1.0, max_open_positions=5)
        e.manage()                                        # records the day's starting equity (10,000)
        for i in (1, 2, 3):
            self.assertEqual(e.handle(entry(i))["status"], "executed")
        b.set_price("GOLD", 3884.00, 3884.30)            # 0.05 + 0.04 + 0.04 lots x 16.30 = -211.9 floating = -2.1%
        e.manage()
        self.assertEqual(b.positions(e.cfg.magic), [], "positions must be flattened at the daily limit")
        self.assertEqual(e.handle(entry(4, price=3884.30))["reason"], "locked_daily_loss")
        # restart: a new engine on the same journal must still be locked, and must not get a fresh loss budget
        e2 = Engine(e.cfg, b, Store(path), clock=lambda: clock[0])
        self.assertEqual(e2.handle(entry(5, price=3884.30))["reason"], "locked_daily_loss")
        b.day = "2026-11-17"                             # next trading day: lock is lifted, new baseline
        self.assertEqual(e2.handle(entry(6, price=3884.30))["status"], "executed")

    def test_total_loss_lock_needs_operator_reset(self):
        e, b, _ = make(max_total_loss_pct=10.0)
        e.manage()
        b.balance = 8900.0                                # -11% from the 10,000 reference
        self.assertEqual(e.handle(entry(1))["reason"], "locked_total_loss")
        b.day = "2026-11-17"
        self.assertEqual(e.handle(entry(2))["reason"], "locked_total_loss")
        e.reset_total_lock()
        self.assertEqual(e.handle(entry(3))["status"], "executed")

    def test_heartbeat_detects_missed_entry(self):
        e, _, _ = make()
        hb = lambda t, total: {"v": 1, "type": "hb", "src": "GOLDV2", "sym": SYM, "t": int(t * 1000), "ready": 1,
                               "session_count": total, "total5": total, "total15": 0, "digest": 1}
        self.assertEqual(e.handle(hb(T0, 3))["reason"], "")
        e.handle(entry(1))
        self.assertEqual(e.handle(hb(T0 + 300, 4))["reason"], "")              # ledger +1, received +1
        self.assertEqual(e.handle(hb(T0 + 600, 5))["reason"], "missed_entry")  # ledger +1, nothing received


if __name__ == "__main__":
    unittest.main()
