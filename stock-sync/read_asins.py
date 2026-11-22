#!/usr/bin/env python3
"""Read-only: price, stock, delivery days and seller of the ASINs listed in stock-sync/read-list.txt (Dubai address).
Usage: python3 -I read_asins.py SHARD NSHARDS outdir     (ASIN i goes to shard i % NSHARDS, list order = priority)
Changes nothing anywhere."""
import datetime as dt
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import amazon_sync as a  # noqa: E402


def main():
    shard, n, outdir = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    asins = [x.strip() for x in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "read-list.txt")) if x.strip()]
    mine = [x for i, x in enumerate(asins) if i % n == shard]
    if not mine:
        return
    os.makedirs(outdir, exist_ok=True)
    out = open(os.path.join(outdir, f"read-{shard}.jsonl"), "w", encoding="utf-8")
    delay = float(os.environ.get("DELAY", "6"))
    a.start_browser()
    print(f"shard {shard}/{n}: {len(mine)} ASINs", flush=True)
    for i, asin in enumerate(mine, 1):
        today = dt.datetime.now(dt.timezone(dt.timedelta(hours=4))).date()
        try:
            pg = a.choose_offer(a.parse(a.fetch(asin), today, asin))
        except Exception as e:  # noqa: BLE001
            pg = {"error": f"{type(e).__name__}: {e}"[:100]}
        rec = {"asin": asin, "title": pg.get("title"), "shade": pg.get("variation"), "pageAsin": pg.get("asin"),
               "redirect": pg.get("redirect"), "gone": pg.get("gone", False), "error": pg.get("error"), "aed": pg.get("aed"),
               "inStock": pg.get("inStock"), "days": pg.get("sourceDays"), "seller": pg.get("seller"),
               "stockLeft": pg.get("stockLeft")}
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out.flush()
        if i % 20 == 0:
            print(f"[{i}/{len(mine)}]", flush=True)
        time.sleep(delay + random.uniform(0, delay / 2))
    out.close()


if __name__ == "__main__":
    main()
