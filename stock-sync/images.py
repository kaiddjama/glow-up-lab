#!/usr/bin/env python3
"""Read-only: for each ASIN of stock-sync/img-list.txt (shard i % N) reads the Amazon.ae page (Dubai address) and writes
the full title, the shade label, the main photo URLs (hiRes) of that very ASIN and the feature bullets.
Usage: python3 -I images.py SHARD NSHARDS outdir      Changes nothing anywhere."""
import datetime as dt
import json
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import amazon_sync as a  # noqa: E402
from families import jsonat  # noqa: E402


def clean(t):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t or "")).strip()


def main():
    shard, n, outdir = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    asins = [x.strip() for x in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "img-list.txt")) if x.strip()]
    mine = [x for i, x in enumerate(asins) if i % n == shard]
    if not mine:
        return
    os.makedirs(outdir, exist_ok=True)
    out = open(os.path.join(outdir, f"img-{shard}.jsonl"), "w", encoding="utf-8")
    delay = float(os.environ.get("DELAY", "6"))
    a.start_browser()
    for i, asin in enumerate(mine, 1):
        today = dt.datetime.now(dt.timezone(dt.timedelta(hours=4))).date()
        rec = {"asin": asin}
        try:
            html = a.fetch(asin)
            pg = a.choose_offer(a.parse(html, today, asin))
            ci = jsonat(html, "colorImages")
            init = (ci or {}).get("initial") if isinstance(ci, dict) else None
            imgs = [x.get("hiRes") or x.get("large") for x in (init or []) if isinstance(x, dict)]
            m = re.search(r'id="productTitle"[^>]*>(.*?)</span>', html, re.S)
            bl = re.search(r'id="feature-bullets"(.*?)</ul>', html, re.S)
            bullets = [clean(x) for x in re.findall(r"<li[^>]*>(.*?)</li>", bl.group(1), re.S)] if bl else []
            rec.update({"title": clean(m.group(1)) if m else pg.get("title"), "shade": pg.get("variation"),
                        "pageAsin": pg.get("asin"), "images": [u for u in imgs if u][:4], "bullets": [b for b in bullets if b][:6],
                        "aed": pg.get("aed"), "days": pg.get("sourceDays"), "seller": pg.get("seller"), "inStock": pg.get("inStock"),
                        "stockLeft": pg.get("stockLeft")})
        except Exception as e:  # noqa: BLE001
            rec["error"] = f"{type(e).__name__}: {e}"[:100]
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out.flush()
        if i % 10 == 0:
            print(f"[{i}/{len(mine)}]", flush=True)
        time.sleep(delay + random.uniform(0, delay / 2))
    out.close()


if __name__ == "__main__":
    main()
