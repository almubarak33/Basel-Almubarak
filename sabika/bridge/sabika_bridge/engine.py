"""Decision engine.

For every incoming message: validate it, apply the risk gates in a fixed order, size the position from the loss at
the stop, send the order with its stop-loss and take-profit attached, and journal the decision with its reason.
The engine, not the signal source, owns the risk: exits never depend on a later message arriving.
"""
import math
import time

from .signals import Heartbeat, SignalError, parse


def _floor_step(value, step):
    """Round DOWN to the volume step (never up)."""
    if step <= 0:
        return 0.0
    return round(math.floor(value / step + 1e-9) * step, 8)


class Engine:
    def __init__(self, cfg, broker, store, clock=time.time):
        self.cfg = cfg
        self.broker = broker
        self.store = store
        self.clock = clock
        self._seq = 0
        self._snapshot = {}

    # ------------------------------------------------------------------ messages
    def handle(self, msg):
        """Process one decoded alert message. Always returns a dict with at least a 'status'."""
        now = self.clock()
        try:
            obj = parse(msg)
        except SignalError as e:
            self._seq += 1
            rid = "invalid-%d-%d" % (int(now * 1000), self._seq)
            self.store.record_message(rid, str(msg.get("src", "?"))[:24] if isinstance(msg, dict) else "?", "invalid", now, msg)
            self.store.set_status(rid, "rejected", str(e))
            return {"status": "rejected", "reason": str(e)}
        if isinstance(obj, Heartbeat):
            return self._heartbeat(obj, now)
        if not self.store.record_message(obj.id, obj.src, "entry", now, msg):
            return {"status": "duplicate", "reason": "already_seen"}
        self.store.set("entries:" + obj.src, int(self.store.get("entries:" + obj.src, 0)) + 1)
        decision = self._decide(obj, now)
        self.store.set_status(obj.id, decision["status"], decision.get("reason", ""), decision.get("detail"))
        return decision

    def _heartbeat(self, hb, now):
        prev = self.store.get("hb:" + hb.src)
        total = int(hb.fields.get("total5", 0) or 0) + int(hb.fields.get("total15", 0) or 0)
        seen = int(self.store.get("entries:" + hb.src, 0))
        warning = ""
        if prev is not None and "total" in prev:
            new_in_ledger = total - int(prev["total"])
            new_received = seen - int(prev.get("seen", 0))
            if new_in_ledger > new_received:
                warning = "missed_entry"
                wid = "warn-%s-%d" % (hb.src, hb.t_ms)
                if self.store.record_message(wid, hb.src, "warning", now, {"ledger_new": new_in_ledger, "received_new": new_received}):
                    self.store.set_status(wid, "warning", warning)
        self.store.set("hb:" + hb.src, {"at": now, "t": hb.t_ms, "total": total, "seen": seen,
                                        "ready": hb.fields.get("ready", 1), "fields": hb.fields})
        return {"status": "heartbeat", "reason": warning}

    # ------------------------------------------------------------------ decision
    def _reject(self, reason, **detail):
        return {"status": "rejected", "reason": reason, "detail": detail}

    def _decide(self, sig, now):
        cfg, risk = self.cfg, self.cfg.risk
        src = cfg.sources.get(sig.src)
        if src is None or not src.enabled:
            return self._reject("source_disabled")
        bsym = cfg.symbols.get(sig.sym)
        if not bsym:
            return self._reject("unknown_symbol", sym=sig.sym)
        age = now - sig.t_ms / 1000.0
        if age > src.max_age_sec:
            return self._reject("stale", age_sec=round(age, 1))
        if age < -5:
            return self._reject("from_future", age_sec=round(age, 1))

        acct = self.broker.account()
        if cfg.mode == "live" and not cfg.live_armed:
            return self._reject("live_not_armed")
        if cfg.mode != "live" and not acct.is_demo:
            return self._reject("real_account_but_mode_is_" + cfg.mode)
        if not acct.trade_allowed:
            return self._reject("trading_disabled_on_account")

        day = self._roll_day(acct)
        lock = self._check_limits(acct, day)
        if lock:
            self._flatten(now, lock)
            return self._reject(lock)

        spec = self.broker.symbol(bsym)
        tick = self.broker.tick(bsym)
        if spec is None:
            return self._reject("symbol_not_found", broker_symbol=bsym)
        if tick is None or tick.bid <= 0 or tick.ask <= 0:
            return self._reject("no_quote", broker_symbol=bsym)

        if len(self.broker.positions(cfg.magic)) >= risk.max_open_positions:
            return self._reject("max_open_positions")
        if len(self.store.trades_on_day(day)) >= risk.max_trades_per_day:
            return self._reject("max_trades_per_day")

        sign = 1 if sig.side == "buy" else -1
        price = tick.ask if sig.side == "buy" else tick.bid
        spread = tick.ask - tick.bid
        model_risk = sign * (sig.entry - sig.sl)
        stop_dist = sign * (price - sig.sl)
        measured = {"price": price, "spread": round(spread, 5), "model_entry": sig.entry, "age_sec": round(age, 1)}
        if stop_dist <= 0:
            return self._reject("price_beyond_stop", **measured)
        chase = sign * (price - sig.entry)
        if abs(chase) > src.max_chase_frac * model_risk:
            return self._reject("price_far_from_model", chase_frac=round(chase / model_risk, 3), **measured)
        if spread > risk.max_spread_frac_of_stop * stop_dist:
            return self._reject("spread_too_wide", spread_frac=round(spread / stop_dist, 3), **measured)
        tp = sig.targets.get(src.tp_field)
        if tp is None:
            return self._reject("missing_target", field=src.tp_field)
        if sign * (tp - price) <= 0:
            return self._reject("target_already_passed", **measured)
        min_dist = spec.stops_level_points * spec.point
        if stop_dist < min_dist or sign * (tp - price) < min_dist:
            return self._reject("inside_broker_stops_level", min_dist=min_dist, **measured)

        # ---- size from the loss at the stop; round down, never up
        base = min(acct.equity, acct.balance)
        risk_money = base * risk.risk_pct / 100.0
        loss_per_lot = self.broker.loss_at_stop(bsym, sig.side, 1.0, price, sig.sl)
        if not loss_per_lot or loss_per_lot <= 0:
            return self._reject("cannot_size", **measured)
        lots = _floor_step(risk_money / loss_per_lot, spec.volume_step)
        notional_cap = _floor_step(risk.max_notional_x_equity * base / (spec.contract_size * price), spec.volume_step)
        binding = "risk"
        for name, cap in (("max_notional", notional_cap), ("max_lots", risk.max_lots), ("broker_max", spec.volume_max)):
            if cap < lots:
                lots, binding = _floor_step(cap, spec.volume_step), name
        if lots < spec.volume_min:
            return self._reject("below_min_lot", risk_money=round(risk_money, 2), binding=binding,
                                loss_at_min_lot=round(loss_per_lot * spec.volume_min, 2), **measured)
        planned_loss = loss_per_lot * lots
        plan = dict(measured, lots=lots, binding=binding, sl=sig.sl, tp=tp, risk_money=round(risk_money, 2),
                    planned_loss=round(planned_loss, 2), chase_frac=round(chase / model_risk, 3))
        if cfg.mode == "monitor":
            return {"status": "monitor_only", "reason": "no_order_sent", "detail": plan}

        res = self.broker.market_order(bsym, sig.side, lots, sig.sl, tp, cfg.magic, sig.id[-27:])
        if not res.ok:
            return {"status": "order_failed", "reason": res.message or str(res.retcode), "detail": dict(plan, retcode=res.retcode)}

        expire_at = now + src.max_hold_min * 60 if src.max_hold_min > 0 else (sig.expire_ms / 1000.0 if sig.expire_ms > 0 else None)
        self.store.add_trade(signal_id=sig.id, src=sig.src, ticket=res.ticket, symbol=bsym, side=sig.side, volume=res.volume or lots,
                             model_entry=sig.entry, fill_price=res.price, sl=sig.sl, tp=tp, risk_money=risk_money,
                             planned_loss=planned_loss, day=day, opened_at=now, expire_at=expire_at)
        # ---- read back: a position without a broker-side stop is closed at once
        pos = next((p for p in self.broker.positions(cfg.magic) if p.ticket == res.ticket), None)
        if pos is not None and pos.sl <= 0:
            closed = self.broker.close(pos)
            if closed.ok:
                self.store.close_trade(sig.id, now, "closed_no_stop")
            return {"status": "closed_no_stop", "reason": "broker_did_not_attach_stop", "detail": dict(plan, ticket=res.ticket, close_ok=closed.ok)}
        return {"status": "executed", "reason": "", "detail": dict(plan, ticket=res.ticket, fill=res.price,
                                                                  slip_frac=round(sign * (res.price - sig.entry) / model_risk, 3))}

    # ------------------------------------------------------------------ limits and day handling
    def _roll_day(self, acct):
        day = self.broker.server_day()
        if self.store.get("day") != day:
            self.store.set("day", day)
            self.store.set("day_start_equity", acct.equity)
        if self.store.get("total_ref_equity") is None:
            self.store.set("total_ref_equity", acct.equity)
        return day

    def _check_limits(self, acct, day):
        """Return a lock reason if a loss limit is (or was) breached, else ''. Locks are persisted."""
        risk = self.cfg.risk
        if self.store.get("lock_total"):
            return "locked_total_loss"
        if self.store.get("lock_day") == day:
            return "locked_daily_loss"
        ref = self.store.get("total_ref_equity")
        if ref and acct.equity <= ref * (1 - risk.max_total_loss_pct / 100.0):
            self.store.set("lock_total", True)
            return "locked_total_loss"
        start = self.store.get("day_start_equity")
        if start and acct.equity <= start * (1 - risk.max_daily_loss_pct / 100.0):
            self.store.set("lock_day", day)
            return "locked_daily_loss"
        return ""

    def _flatten(self, now, reason):
        """Close every position this bridge owns. Returns how many are still open."""
        left = 0
        by_ticket = {t["ticket"]: t for t in self.store.open_trades()}
        for pos in self.broker.positions(self.cfg.magic):
            if self.broker.close(pos).ok:
                if pos.ticket in by_ticket:
                    self.store.close_trade(by_ticket[pos.ticket]["signal_id"], now, "flatten_" + reason)
            else:
                left += 1
        return left

    def reset_total_lock(self):
        """Operator action: clear the total-loss lock and take the current equity as the new reference."""
        acct = self.broker.account()
        self.store.set("lock_total", False)
        self.store.set("total_ref_equity", acct.equity)

    # ------------------------------------------------------------------ periodic management
    def manage(self):
        """Call every few seconds: loss limits, time exits, reconciliation with the broker, naked-position check."""
        now = self.clock()
        acct = self.broker.account()
        day = self._roll_day(acct)
        lock = self._check_limits(acct, day)
        if lock:
            self._flatten(now, lock)
        positions = {p.ticket: p for p in self.broker.positions(self.cfg.magic)}
        for t in self.store.open_trades():
            pos = positions.get(t["ticket"])
            if pos is None:
                self.store.close_trade(t["signal_id"], now, "closed_at_broker")       # stop or target was hit
            elif t["expire_at"] and now >= t["expire_at"]:
                if self.broker.close(pos).ok:
                    self.store.close_trade(t["signal_id"], now, "time_exit")
        for pos in self.broker.positions(self.cfg.magic):
            if pos.sl <= 0:                                                          # never leave a position unprotected
                self.broker.close(pos)
        self._snapshot = {"at": now, "equity": acct.equity, "balance": acct.balance, "day": day, "lock": lock,
                          "open_positions": len(self.broker.positions(self.cfg.magic))}
        return self._snapshot

    def status(self):
        """Read-only summary built from the journal and the last manage() snapshot (safe to call from another thread)."""
        now = self.clock()
        hb = {}
        for name in self.cfg.sources:
            h = self.store.get("hb:" + name)
            if h:
                age = now - h["at"]
                hb[name] = {"age_sec": round(age, 1), "ready": h.get("ready", 1), "stale": age > self.cfg.heartbeat_timeout_sec}
        return {"mode": self.cfg.mode, "snapshot": self._snapshot, "day_start_equity": self.store.get("day_start_equity"),
                "total_ref_equity": self.store.get("total_ref_equity"), "lock_total": bool(self.store.get("lock_total")),
                "lock_day": self.store.get("lock_day"), "heartbeats": hb, "open_trades": self.store.open_trades(),
                "recent": self.store.recent_messages(15)}
