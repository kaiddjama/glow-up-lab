#!/usr/bin/env python3
"""The clock of the shop's controls.

GitHub's own schedule ("cron") is not a clock: measured on 10 Nov, the 10-minute controls ran 15 to 75 minutes apart and a
full stock check started up to 3 hours late or not at all. This script is a clock that does not depend on it: one small
job that stays awake, starts each control when it is due (GitHub starts a control asked for this way at once), and hands
over to a fresh copy of itself before GitHub's time limit for a job. The schedules stay in the workflows as a second chance.

  python3 -I heartbeat.py loop [minutes]   stay awake for that long (default 175) and start the controls that are due
  python3 -I heartbeat.py ensure           start a clock if none is running, replace one that stopped doing its work
  python3 -I heartbeat.py gate             for stock-sync.yml: should this full check run? (no if another full check
                                           started less than GATE_MIN minutes ago and went well or is still running)
Needs GITHUB_TOKEN with "actions: write" and GITHUB_REPOSITORY. HEARTBEAT_DRY=1 starts nothing and only says what it would do.
A control is never started twice: before starting one, the clock looks at when it last ran, whoever started it.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
REPO = os.environ.get("GITHUB_REPOSITORY", "")
REF = os.environ.get("TARGET_REF") or "main"
DRY = os.environ.get("HEARTBEAT_DRY") == "1"
BEAT = "heartbeat.yml"
SYNC = "stock-sync.yml"
FULL_TITLE = "Contrôle complet du stock"  # run-name of a real full check in stock-sync.yml
# workflow file, minutes between two runs, minute of the hour of the first one
JOBS = (("order-check.yml", 10, 4), ("medx-sync.yml", 10, 7), ("fallback-sync.yml", 10, 1),
        ("padelshop-sync.yml", 30, 27), ("inventory-audit.yml", 30, 23),
        # runs started by this clock (GITHUB_TOKEN) never fire workflow_run, so park-soldout no longer followed the order
        # checks: the clock starts it itself every 30 min (10 Nov: not run for over 2 h)
        ("park-soldout.yml", 30, 11))
EARLY = 0.7  # a control that ran less than this share of its interval ago is not started again
SYNC_GRACE_MIN = 12  # a full check is started by the clock when GitHub has not started it this long after its hour
SYNC_WINDOW_MIN = 150  # ...and no longer started when its hour is this far behind (the next one is close)
GATE_MIN = 120
STUCK_MIN = 25  # a clock that has been running this long while no order check started in that time is replaced
MAX_FAILS = 6  # start requests refused in a row before the clock gives up and alerts


def now():
    return dt.datetime.now(dt.timezone.utc)


def when(text):
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def minutes_since(text, t=None):
    return ((t or now()) - when(text)).total_seconds() / 60 if text else None


def api(method, path, body=None):
    req = urllib.request.Request(
        f"{API}/repos/{REPO}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "stock-heartbeat"})
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read()
    return json.loads(text) if text else {}


def runs_of(workflow, n=5):
    """The latest runs of a workflow, newest first; None when the workflow does not exist (yet) in the repository."""
    try:
        return api("GET", f"/actions/workflows/{workflow}/runs?per_page={n}").get("workflow_runs", [])
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def start(workflow, inputs=None):
    """Asks GitHub to start a workflow now. True when accepted."""
    if DRY:
        print(f"DRY: would start {workflow} {inputs or ''}", flush=True)
        return True
    try:
        api("POST", f"/actions/workflows/{workflow}/dispatches", {"ref": REF, "inputs": inputs or {}})
        print(f"{now():%H:%M:%S} started {workflow}", flush=True)
        return True
    except (urllib.error.URLError, OSError) as e:
        print(f"::warning::{workflow} could not be started ({e})", flush=True)
        return False


def due(runs, interval, t=None):
    """Pure: should a control with these latest runs be started now?"""
    if not runs:
        return True
    age = min(minutes_since(r["created_at"], t) for r in runs)
    return age >= EARLY * interval


def sync_hours(path=None):
    """(hour, minute) UTC of the full checks, read from the schedule lines of stock-sync.yml: one source of truth."""
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".github", "workflows", SYNC)
    return sorted({(int(h), int(m)) for m, h in re.findall(r'cron:\s*"(\d+) (\d+) \* \* \*"', open(path).read())})


def sync_due(hours, runs, t):
    """Pure: the scheduled time of a full check that should have started and has not, or None."""
    for day in (t.date(), t.date() - dt.timedelta(days=1)):
        for h, m in hours:
            at = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=dt.timezone.utc)
            late = (t - at).total_seconds() / 60
            if not SYNC_GRACE_MIN <= late <= SYNC_WINDOW_MIN:
                continue
            done = [r for r in runs or [] if (r.get("display_title") or "").startswith(FULL_TITLE)
                    and when(r["created_at"]) >= at - dt.timedelta(minutes=10)]
            if not done:
                return at
    return None


def gate_blocks(runs, me, t):
    """Pure: the reason not to run a full check now, or None."""
    for r in runs or []:
        if r["id"] == me or not (r.get("display_title") or "").startswith(FULL_TITLE):
            continue
        started = r.get("run_started_at") or r["created_at"]
        if minutes_since(started, t) > GATE_MIN:
            continue
        if r["status"] != "completed":
            return f"another full check is still running (run {r['id']})"
        if r.get("conclusion") == "success" and minutes_since(started, when(r["updated_at"])) >= 15:
            return f"a full check started {minutes_since(started, t):.0f} min ago and went well (run {r['id']})"
    return None


def gate():
    go, why = True, "nothing recent"
    try:
        if os.environ.get("FULL_RUN") == "1":
            why = gate_blocks(runs_of(SYNC, 20), int(os.environ.get("GITHUB_RUN_ID", "0")), now())
            go, why = (False, why) if why else (True, "no recent full check")
        else:
            why = "trial or partial run: always allowed"
    except Exception as e:  # the gate never stops a check because GitHub's API hiccuped
        why = f"gate could not look ({type(e).__name__}): running"
    print(f"Run this check: {go} ({why})")
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as f:
        f.write(f"go={'true' if go else 'false'}\nt0={now():%Y-%m-%dT%H:%M:%SZ}\n")


def clocks(me=0):
    """The clock runs that are not finished (running or waiting for their turn), without this one."""
    runs = runs_of(BEAT, 20)
    if runs is None:
        return None
    return [r for r in runs if r["event"] == "workflow_dispatch" and r["status"] != "completed" and r["id"] != me]


def ensure(me=0):
    """One clock must be alive. Returns what was done."""
    alive = clocks(me)
    if alive is None:
        return "the clock workflow is not in the repository yet"
    for r in alive:
        if r["status"] != "in_progress" or minutes_since(r.get("run_started_at") or r["created_at"]) < STUCK_MIN:
            continue
        orders = runs_of("order-check.yml", 1)
        if orders and minutes_since(orders[0]["created_at"]) < STUCK_MIN:
            continue
        print(f"::warning::clock run {r['id']} is running but started no order check for {STUCK_MIN} min: replaced")
        if not DRY:
            try:
                api("POST", f"/actions/runs/{r['id']}/cancel")
            except urllib.error.HTTPError as e:
                print("cancel refused:", e.code)
        return "replaced a stuck clock" if start(BEAT) else sys.exit("ALERTE: the clock is stuck and could not be replaced.")
    if alive:
        return f"a clock is alive (run {alive[0]['id']}, {alive[0]['status']})"
    return "started a clock" if start(BEAT) else sys.exit("ALERTE: no clock is running and none could be started.")


def next_slot(t, interval, offset):
    """The next minute of the hour, after t, on which a control with this interval and offset runs."""
    base = t.replace(second=0, microsecond=0)
    for k in range(1, 61):
        cand = base + dt.timedelta(minutes=k)
        if cand.minute % interval == offset % interval:
            return cand
    return base + dt.timedelta(minutes=interval)


def loop(minutes):
    me = int(os.environ.get("GITHUB_RUN_ID", "0"))
    hours = sync_hours()
    print(f"Clock awake for {minutes:g} min on {REF}; full checks at (UTC) {hours}; dry={DRY}", flush=True)
    t0, fails, successor, asked = now(), 0, False, set()
    nxt = {wf: t0 for wf, _, _ in JOBS}  # first look at once, then on each control's own minutes
    next_sync = t0
    while (now() - t0).total_seconds() < minutes * 60:
        t = now()
        try:
            if not successor:  # the next clock waits in line behind this one and takes over when it ends, however it ends
                successor = bool(clocks(me)) or start(BEAT)
            for wf, interval, offset in JOBS:
                if t < nxt[wf]:
                    continue
                nxt[wf] = next_slot(t, interval, offset)
                runs = runs_of(wf, 3)
                if runs is None:  # not known to GitHub (yet): looked at again in half an hour
                    nxt[wf] = t + dt.timedelta(minutes=30)
                    print(f"{wf} is not in the repository: left out for 30 min", flush=True)
                elif due(runs, interval, t):
                    fails = 0 if start(wf, {"dry_run": "false"}) else fails + 1
            if t >= next_sync:
                next_sync = t + dt.timedelta(minutes=5)
                at = sync_due(hours, runs_of(SYNC, 20), t)
                if at and at not in asked:
                    print(f"The full check of {at:%H:%M} UTC has not started: starting it", flush=True)
                    if start(SYNC, {"dry_run": "false"}):
                        asked.add(at)
                    else:
                        fails += 1
        except Exception as e:  # GitHub's API not answering: try again at the next tick
            fails += 1
            print(f"::warning::tick failed ({type(e).__name__}: {str(e)[:120]})", flush=True)
        if fails >= MAX_FAILS:
            sys.exit(f"ALERTE: the clock could not start the controls {fails} times in a row.")
        time.sleep(20)
    print("Handing over:", ensure(me))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "ensure"
    if mode == "gate":
        return gate()
    if not (REPO and os.environ.get("GITHUB_TOKEN")):
        sys.exit("ALERTE: GITHUB_TOKEN / GITHUB_REPOSITORY missing: the clock cannot work.")
    if mode == "loop":
        return loop(float(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else 175)
    print("Clock check:", ensure(int(os.environ.get("GITHUB_RUN_ID", "0"))))


if __name__ == "__main__":
    main()
