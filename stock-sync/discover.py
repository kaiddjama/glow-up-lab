#!/usr/bin/env python3
"""Read-only discovery of the current Amazon.ae catalogue of a brand (search result pages, Dubai address).

Usage: python3 -I discover.py SHARD NSHARDS outdir        (tasks = brand x search term x page, split by shard)
Prints one JSON line per search result: brand query, term, asin, title, price, sponsored. Changes nothing anywhere.
"""
import json
import os
import random
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import amazon_sync as a  # noqa: E402

ALL = {"huda": "huda beauty", "nyx": "nyx professional makeup", "elf": "e.l.f. cosmetics", "essence": "essence cosmetics", "rt": "real techniques", "purple": "purple shampoo", "silver": "silver shampoo grey hair", "noyellow": "anti yellow shampoo", "swim": "swimmers chlorine shampoo"}
BRANDS = {k: v for k, v in ALL.items() if k in os.environ.get("BRAND_KEYS", "huda,nyx,elf,essence").split(",")}
TERMS = ["", "foundation", "concealer", "setting powder", "powder", "blush", "bronzer", "highlighter", "contour",
         "lipstick", "lip gloss", "lip liner", "lip oil", "lip balm", "eyeliner", "mascara", "eyeshadow palette",
         "brow", "primer", "setting spray", "makeup brush", "lashes", "skin tint", "tinted moisturizer", "kohl pencil",
         "face palette", "cream blush", "lip plumper", "cleanser", "skincare"]
TERMS = [x.strip() for x in os.environ["TERMS"].split(",")] if os.environ.get("TERMS") else TERMS  # TERMS="a,b" overrides
PAGES = (1, 2, 3)
JS = """() => [...document.querySelectorAll('div[data-component-type="s-search-result"]')].map(d => ({
  asin: d.getAttribute('data-asin'),
  title: (d.querySelector('h2') || {}).innerText || '',
  price: ((d.querySelector('.a-price .a-offscreen') || {}).textContent || ''),
  sponsored: /Sponsored/i.test(d.innerText.slice(0, 200)),
  more: (d.innerText.match(/\\+\\s*\\d+\\s*(colou?rs?|sizes?|options?)/i) || [''])[0]
}))"""


def main():
    shard, n, outdir = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    tasks = [(b, t, p) for b in BRANDS for t in TERMS for p in PAGES if not (t == "" and p > 7)]
    mine = [x for i, x in enumerate(tasks) if i % n == shard]
    os.makedirs(outdir, exist_ok=True)
    out = open(os.path.join(outdir, f"discover-{shard}.jsonl"), "w", encoding="utf-8")
    delay = float(os.environ.get("DELAY", "6"))
    a.start_browser()
    p = a.READER.page
    print(f"shard {shard}/{n}: {len(mine)} search pages", flush=True)
    for i, (b, term, pg) in enumerate(mine, 1):
        q = f"{BRANDS[b]} {term}".strip()
        url = "https://www.amazon.ae/s?" + urllib.parse.urlencode({"k": q, "language": "en_AE", "page": pg})
        try:
            p.goto(url, wait_until="domcontentloaded")
            a.READER._clear_gate()
            try:
                p.wait_for_selector('div[data-component-type="s-search-result"]', timeout=15000)
            except Exception:
                pass
            p.wait_for_timeout(1200)
            res = p.evaluate(JS)
        except Exception as e:  # noqa: BLE001
            print("ERR", q, pg, f"{type(e).__name__}: {e}"[:120], flush=True)
            res = []
        print(f"[{i}/{len(mine)}] {q!r} page {pg}: {len(res)} results", flush=True)
        for r in res:
            if r["asin"]:
                line = json.dumps({"brand": b, "q": q, "page": pg, **r}, ensure_ascii=False)
                out.write(line + "\n")
                print("ROW", line, flush=True)
        out.flush()
        time.sleep(delay + random.uniform(0, delay / 2))
    out.close()


if __name__ == "__main__":
    main()
