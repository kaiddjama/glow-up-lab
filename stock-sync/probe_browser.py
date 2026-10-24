#!/usr/bin/env python3
"""Test whether a real headless browser reads Amazon.ae from this machine (no Shopify access, nothing is changed).

Usage: python3 probe_browser.py ASIN [ASIN ...]
Sets the Dubai delivery location, reads each product page slowly and prints what amazon_sync.py would see:
price, stock, seller, delivery date, plus how many pages were blocked.
"""
import datetime as dt
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("BROWSER_DEBUG", "1")
import amazon_sync as a  # noqa: E402
import browser_fetch as b  # noqa: E402


def main():
    asins = sys.argv[1:]
    delay = float(os.environ.get("DELAY", "8"))
    today = dt.date.today()
    start = time.time()
    ok = blocked = other = 0
    with b.BrowserReader() as r:
        print("Location:", r.location_text())
        for n, asin in enumerate(asins, 1):
            try:
                pg = a.parse(r.get(f"https://www.amazon.ae/dp/{asin}?language=en_AE"), today)
            except Exception as e:
                pg = {"error": f"{type(e).__name__}: {e}"[:100]}
            if pg.get("error") == "captcha":
                blocked += 1
            elif pg.get("error"):
                other += 1
            else:
                ok += 1
            print(n, asin, {k: pg.get(k) for k in ("error", "aed", "inStock", "seller", "deliveryText", "sourceDays")}, flush=True)
            time.sleep(delay + random.uniform(0, delay / 2))
        print("Location at the end:", r.location_text())
    print(f"read {ok}, captcha {blocked}, other errors {other}, of {len(asins)} in {int(time.time() - start)} s")


if __name__ == "__main__":
    main()
