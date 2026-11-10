#!/usr/bin/env python3
"""Offline tests of the clock (heartbeat.py), of the coverage decisions and of the second-source check.
Run: python3 -I test_heartbeat.py"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import amazon_sync as s  # noqa: E402
import coverage as c  # noqa: E402
import fallback_sync as fb  # noqa: E402
import heartbeat as h  # noqa: E402
import suppliers  # noqa: E402

T = dt.datetime(2026, 11, 10, 10, 30, tzinfo=dt.timezone.utc)


def ago(minutes):
    return (T - dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(minutes, title=h.FULL_TITLE, status="completed", conclusion="success", lasted=45, rid=1, event="schedule"):
    return {"id": rid, "created_at": ago(minutes), "run_started_at": ago(minutes), "updated_at": ago(minutes - lasted),
            "status": status, "conclusion": conclusion, "display_title": title, "event": event}


def test_clock():
    assert h.due([], 10, T) and h.due([run(8)], 10, T) and not h.due([run(5)], 10, T)
    assert h.next_slot(T, 10, 4).minute == 34 and h.next_slot(T.replace(minute=34), 10, 4).minute == 44
    hours = h.sync_hours()
    assert (10, 7) in hours and len(hours) == 5, hours
    # 10:07 check: 23 min late and nothing started -> the clock starts it; a run started at 10:09 -> nothing to do
    assert h.sync_due(hours, [run(300)], T) == dt.datetime(2026, 11, 10, 10, 7, tzinfo=dt.timezone.utc)
    assert h.sync_due(hours, [run(21)], T) is None
    assert h.sync_due(hours, [run(21, title="Essai ou contrôle partiel")], T) is not None  # a trial does not count
    assert h.sync_due(hours, [], T.replace(minute=10)) is None  # 3 min late: GitHub may still start it
    assert h.sync_due(hours, [run(900)], T.replace(hour=13, minute=0)) is None  # too far behind: the next one is close


def test_gate():
    assert h.gate_blocks([run(60, rid=2)], 1, T)  # a full check that went well an hour ago: this one is dropped
    assert h.gate_blocks([run(30, status="in_progress", conclusion=None, rid=2)], 1, T)
    assert not h.gate_blocks([run(60, rid=1)], 1, T)  # itself
    assert not h.gate_blocks([run(60, conclusion="failure", rid=2)], 1, T)  # a failed one is done again
    assert not h.gate_blocks([run(60, lasted=1, rid=2)], 1, T)  # a run the gate dropped (a minute long) does not count
    assert not h.gate_blocks([run(200, rid=2)], 1, T) and not h.gate_blocks([run(60, title="Essai", rid=2)], 1, T)


def test_coverage():
    def v(age, asin="B0AAAAAAAA"):
        return {"product": "p", "variant": "v", "label": "l", "asin": asin, "seen": None, "age": age}
    hide, alerts = c.decide([v(1)] * 300 + [v(7)] * 10 + [v(None)] * 2 + [v(1, None)] * 3, 2)
    assert len(hide) == 15 and not alerts  # a few unread pages: hidden quietly
    hide, alerts = c.decide([v(1)] * 100 + [v(8)] * 150 + [v(13)] * 5, 2)
    assert len(hide) == 5 and len(alerts) == 2  # reading broken: alert, only what is 12 h old is hidden
    hide, alerts = c.decide([v(1)] * 300 + [v(1, None)] * 200)
    assert not hide and len(alerts) == 1  # hundreds without an ASIN: a data problem, alert only


def test_second_source():
    mod = suppliers.module_of("PSAE-x")[0]
    good = {"aed": 300.0, "qty": 1, "available": True, "publish": True}
    s.MARGIN_CUSTOMS, s.SHIPPING_AED_PER_KG, s.AED_TO_FDJ = 2.0, 10.0, 50.0
    r = {"policy": "CONTINUE", "fallback": "PSAE-x", "price": float(s.formula(300.0, 200)), "grams": 200,
         "state": {"src": "PSAE-x", "src_t": ago(20)}}
    what, price, state = fb.decide(r, good, mod, T)
    assert what == "refresh" and price is None and state["src_t"] == s.iso(T)
    assert fb.decide(r, {**good, "available": False}, mod, T)[0] == "stop"
    assert fb.decide(r, {"error": "HTTP 503"}, mod, T)[0] == "keep"
    old = {**r, "state": {"src": "PSAE-x", "src_t": ago(60 * mod.STALE_HOURS + 30)}}
    assert fb.decide(old, {"error": "HTTP 503"}, mod, T)[0] == "stop"
    assert fb.decide({**r, "fallback": ""}, good, mod, T)[0] == "stop"  # reference removed by hand


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("heartbeat, coverage and second-source tests OK")
