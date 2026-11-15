#!/usr/bin/env python3
"""Read-only audit: names of the shades/sizes in the shop vs what Amazon.ae shows today, for chosen brands.

Usage: python3 -I shade_audit.py SHARD NSHARDS outdir
Env: VENDORS (comma-separated Shopify vendor search terms), DELAY. Changes nothing on Shopify (queries only).
Prints one JSON line per ASIN: shop product/variant name, page title, selected shade, page ASIN, price, stock, state.
"""
import datetime as dt
import json
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import amazon_sync as a  # noqa: E402

Q = """query($after:String,$q:String!){ products(first:50, after:$after, query:$q){
  pageInfo{hasNextPage endCursor}
  nodes{ handle title vendor status variants(first:100){ nodes{ id title sku inventoryPolicy } } } } }"""
ASIN = re.compile(r"^B[0-9A-Z]{9}$")


def shop_rows():
    rows, seen = [], set()
    for term in os.environ["VENDORS"].split(","):
        after = None
        while True:
            d = a.gql(Q, {"after": after, "q": term.strip()})["products"]
            for p in d["nodes"]:
                for v in p["variants"]["nodes"]:
                    sku = (v.get("sku") or "").strip()
                    if ASIN.match(sku) and sku not in seen:
                        seen.add(sku)
                        rows.append({"asin": sku, "handle": p["handle"], "product": p["title"], "vendor": p["vendor"],
                                     "status": p["status"], "variant": v["title"], "policy": v["inventoryPolicy"]})
            if not d["pageInfo"]["hasNextPage"]:
                break
            after = d["pageInfo"]["endCursor"]
    return sorted(rows, key=lambda r: r["asin"])


def main():
    shard, n, outdir = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    if not a.have_credentials():
        return
    rows = shop_rows()
    mine = [r for i, r in enumerate(rows) if i % n == shard]
    print(f"shard {shard}/{n}: {len(mine)} of {len(rows)} ASINs", flush=True)
    os.makedirs(outdir, exist_ok=True)
    delay = float(os.environ.get("DELAY", "8"))
    a.start_browser()
    out = open(os.path.join(outdir, f"shard-{shard}.jsonl"), "w", encoding="utf-8")
    for i, r in enumerate(mine, 1):
        today = dt.datetime.now(dt.timezone(dt.timedelta(hours=4))).date()
        try:
            pg = a.choose_offer(a.parse(a.fetch(r["asin"]), today, r["asin"]))
        except Exception as e:  # noqa: BLE001
            pg = {"error": f"{type(e).__name__}: {e}"[:100]}
        if pg.get("error") == "location" and a.READER:
            a.READER.set_location()
        rec = {**r, "pageTitle": pg.get("title"), "pageShade": pg.get("variation"), "pageAsin": pg.get("asin"),
               "redirect": pg.get("redirect"), "gone": pg.get("gone", False), "error": pg.get("error"),
               "aed": pg.get("aed"), "inStock": pg.get("inStock"), "days": pg.get("sourceDays"),
               "seller": pg.get("seller")}
        line = json.dumps(rec, ensure_ascii=False)
        out.write(line + "\n")
        out.flush()
        print("ROW", line, flush=True)
        time.sleep(delay + random.uniform(0, delay / 2))
    out.close()


if __name__ == "__main__":
    main()
