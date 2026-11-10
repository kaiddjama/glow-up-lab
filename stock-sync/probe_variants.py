#!/usr/bin/env python3
"""Lists the variations (flavours) of Amazon.ae listings and reads each one like the stock sync does (no Shopify access,
nothing is changed). Usage: python3 probe_variants.py SEED_ASIN [SEED_ASIN ...]
For each seed page: title, the variation ASINs with their labels (twister data), then for every variation ASIN:
price, stock, seller, free delivery date, first image URL. Slow on purpose (DELAY seconds + jitter), max MAX_PAGES pages.
"""
import datetime as dt
import json
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("BROWSER_DEBUG", "0")
import amazon_sync as a  # noqa: E402
import browser_fetch as b  # noqa: E402


def title(html):
    m = re.search(r'id="productTitle"[^>]*>(.*?)</span>', html, re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else None


def twister(html):
    """{asin: [labels]} from the page's dimensionValuesDisplayData, {} if absent."""
    i = html.find('"dimensionValuesDisplayData"')
    if i < 0:
        return {}
    j = html.find("{", i)
    depth = 0
    for k in range(j, min(len(html), j + 60000)):
        depth += (html[k] == "{") - (html[k] == "}")
        if depth == 0:
            try:
                return json.loads(html[j:k + 1])
            except ValueError:
                return {}
    return {}


def image(html):
    m = re.search(r'"hiRes"\s*:\s*"(https://[^"]+)"', html) or re.search(r'"large"\s*:\s*"(https://[^"]+)"', html)
    return m.group(1) if m else None


def main():
    seeds = sys.argv[1:]
    delay = float(os.environ.get("DELAY", "8"))
    max_pages = int(os.environ.get("MAX_PAGES", "40"))
    today = dt.date.today()
    queries = [x[2:] for x in seeds if x.startswith("q:")]
    seeds = [x for x in seeds if not x.startswith("q:")]
    todo, seen, n = list(seeds), set(), 0
    labels = {}
    with b.BrowserReader() as r:
        print("Location:", r.location_text(), flush=True)
        for q in queries:  # search page: prints the ASIN and title of each result, nothing else
            r.page.goto("https://www.amazon.ae/s?language=en_AE&k=" + q.replace(" ", "+"), wait_until="domcontentloaded")
            r.page.wait_for_timeout(4000)
            for it in r.page.locator("div[data-component-type='s-search-result'][data-asin]").all()[:24]:
                t = re.sub(r"\s+", " ", it.inner_text())[:110]
                print("SEARCH", q, "|", it.get_attribute("data-asin"), "|", t, flush=True)
            time.sleep(delay)
        while todo and n < max_pages:
            asin = todo.pop(0)
            if asin in seen:
                continue
            seen.add(asin)
            n += 1
            try:
                html = r.get(f"https://www.amazon.ae/dp/{asin}?language=en_AE")
                pg = a.parse(html, today)
                tw = twister(html) if asin in seeds else {}
                row = {"asin": asin, "title": title(html), "image": image(html), "labels": tw.get(asin),
                       **{k: pg.get(k) for k in ("error", "aed", "inStock", "availability", "seller", "deliveryText", "sourceDays")}}
                if tw:
                    labels.update(tw)
                    print("TWISTER", json.dumps(tw), flush=True)
                    todo += [x for x in tw if x not in seen]
            except Exception as e:
                row = {"asin": asin, "error": f"{type(e).__name__}: {e}"[:120]}
            print("RESULT", json.dumps(row, ensure_ascii=False), flush=True)
            time.sleep(delay + random.uniform(0, delay / 2))
    print("pages read:", n, "| left unread:", len(todo))


if __name__ == "__main__":
    main()
