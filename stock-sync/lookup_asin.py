#!/usr/bin/env python3
"""One-off Amazon.ae lookup: finds listings by search text and prints ASIN, price, seller, delivery, weight and images.

Usage: python3 lookup_asin.py queries.txt   (one "BRAND | search text" per line)
Read-only: nothing is written anywhere except the job log.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse

import amazon_sync as a


def get(url):
    req = a.urllib.request.Request(url, headers={"User-Agent": a.UA, "Accept-Language": "en-AE,en;q=0.9"})
    with a.urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def search(text):
    html = get("https://www.amazon.ae/s?k=" + urllib.parse.quote_plus(text) + "&language=en_AE")
    out = []
    for block in html.split('data-component-type="s-search-result"')[1:]:
        asin = re.search(r'data-asin="(B0[A-Z0-9]{8})"', block)
        title = re.search(r"<h2[^>]*>(.*?)</h2>", block, re.S)
        if asin and title:
            flat = re.sub(r"<[^>]+>|\s+", " ", block)
            price = re.search(r'a-offscreen">\s*(?:AED|د\.إ\.?)\s*(?:&nbsp;)?\s*([\d,]+\.?\d*)', block)
            deliv = re.search(r"(?:delivery|Delivery)\s+([A-Z][a-z]{2},? \d{1,2} [A-Z][a-z]{2}|Tomorrow|Today)", flat)
            img = re.search(r'src="(https://m\.media-amazon\.com/images/I/[^"]+)"', block)
            out.append((asin.group(1), re.sub(r"<[^>]+>|\s+", " ", title.group(1)).strip(),
                        {"aed": price.group(1) if price else None, "delivery": deliv.group(1) if deliv else None,
                         "img": img.group(1) if img else None}))
    return out


def details(html):
    w = re.search(r"Item Weight\s*</th>\s*<td[^>]*>\s*([^<]+)", html, re.S) or \
        re.search(r"Item Weight[^<]*</span>\s*<span[^>]*>\s*([^<]+)", html, re.S)
    imgs = list(dict.fromkeys(re.findall(r'"hiRes":"(https://m\.media-amazon\.com/images/I/[^"]+)"', html)))
    return {"weight": w.group(1).strip() if w else None, "images": imgs[:8]}


def main(path):
    today = dt.date.today()
    for line in open(path, encoding="utf-8"):
        if "|" not in line:
            continue
        brand, text = [s.strip() for s in line.split("|", 1)]
        print(f"\n=== {brand} : {text}", flush=True)
        results = []
        for attempt in range(4):
            try:
                results = search(text)
                break
            except Exception as e:  # noqa: BLE001
                print("search failed:", e)
                time.sleep(20)
        for asin, title, info in results[:10]:
            print("  candidate", asin, title[:110], json.dumps(info))
        picks = [] if os.environ.get("SKIP_PAGES") else [r for r in results if brand.lower() in r[1].lower() or "matcha" in r[1].lower()][:3]
        for asin, title, _ in picks:
            page = {"error": "no try"}
            for attempt in range(3):
                time.sleep(15)
                try:
                    html = a.fetch(asin)
                    page = a.parse(html, today)
                    page.update(details(html))
                    if "error" not in page:
                        break
                except Exception as e:  # noqa: BLE001
                    page = {"error": str(e)}
            print("  PAGE", asin, title[:80])
            print("  ", json.dumps(page, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
