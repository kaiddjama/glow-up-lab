#!/usr/bin/env python3
"""Look up a product on Amazon.ae with the Dubai browser (nothing is changed anywhere).

Usage: python3 lookup.py "search words" [must-contain word ...]
Searches Amazon.ae, keeps the results whose title has every must-contain word, then reads each product page and
prints title, price, stock, seller, delivery, weight and main image.
"""
import datetime as dt
import html as htmllib
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("BROWSER_DEBUG", "1")
import amazon_sync as a  # noqa: E402
import browser_fetch as b  # noqa: E402


def search(r, query):
    r.page.goto("https://www.amazon.ae/s?language=en_AE&k=" + urllib.parse.quote_plus(query), wait_until="domcontentloaded")
    r._clear_gate()
    r.page.wait_for_timeout(3000)
    out = []
    for card in r.page.locator("div[data-component-type='s-search-result'][data-asin]").all()[:20]:
        asin = card.get_attribute("data-asin")
        if not asin:
            continue
        title = re.sub(r"\s+", " ", card.inner_text()[:300])
        out.append((asin, title))
    return out


def details(page_html):
    def grab(pat):
        m = re.search(pat, page_html, re.S)
        return htmllib.unescape(re.sub(r"<[^>]+>|\s+", " ", m.group(1))).strip() if m else None
    img = re.search(r'"hiRes":"(https:[^"]+)"', page_html) or re.search(r'id="landingImage"[^>]*src="([^"]+)"', page_html)
    return {"title": grab(r'id="productTitle"[^>]*>(.*?)</span>'),
            "brand": grab(r'id="bylineInfo"[^>]*>(.*?)</a>'),
            "weight": grab(r'(?:Item Weight|Item weight)</(?:th|span)>\s*<(?:td|span)[^>]*>(.*?)</(?:td|span)>'),
            "image": img.group(1) if img else None}


def main():
    query, must = sys.argv[1], [w.lower() for w in sys.argv[2:]]
    today = dt.date.today()
    with b.BrowserReader() as r:
        print("Location:", r.location_text())
        hits = search(r, query)
        print("Search results:")
        for asin, t in hits:
            print(" ", asin, t[:160])
        picks = [h for h in hits if all(w in h[1].lower() for w in must)][:3]
        print("Reading:", [p[0] for p in picks])
        for asin, _ in picks:
            htm = r.get(f"https://www.amazon.ae/dp/{asin}?language=en_AE")
            pg = a.parse(htm, today)
            print(asin, {**{k: pg.get(k) for k in ("error", "aed", "inStock", "availability", "seller", "deliveryText", "sourceDays")}, **details(htm)}, flush=True)
            time.sleep(6)
        print("Location at the end:", r.location_text())


if __name__ == "__main__":
    main()
