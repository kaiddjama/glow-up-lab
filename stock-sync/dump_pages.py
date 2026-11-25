#!/usr/bin/env python3
"""Read-only: reads the listed Amazon.ae pages (Dubai address) and prints one `NP {json}` line per ASIN: full title, seller,
price, stock, delivery days, main photos (hiRes), bullets, rating, and the passages that mention gelatin / halal / vegan / pectin /
bovine / porcine... (for the halal check of supplements). Usage: python3 -I dump_pages.py outdir ASIN..."""
import gzip
import json
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import amazon_page as ap  # noqa: E402
import amazon_sync as a  # noqa: E402

KEY = re.compile(r"(gelatin\w*|halal|vegan|vegetarian|pectin|bovine|porcine|pork|beef|capsule shell|softgel capsule|"
                 r"other ingredients|ingredients ?:)", re.I)


def snippets(text, limit=10):
    out, last = [], -1000
    for m in KEY.finditer(text):
        if m.start() - last < 180:
            continue
        last = m.start()
        out.append(text[max(0, m.start() - 90):m.end() + 140])
        if len(out) >= limit:
            break
    return out


def main():
    os.makedirs(sys.argv[1], exist_ok=True)
    a.start_browser()
    for asin in sys.argv[2:]:
        rec = {"asin": asin}
        try:
            html = a.fetch(asin)
            with gzip.open(os.path.join(sys.argv[1], f"{asin}.html.gz"), "wt", encoding="utf-8") as f:
                f.write(html)
            pg = a.choose_offer(ap.parse(html, ap.dubai_today(), asin))
            i0 = html.find("'colorImages'")
            seg = html[i0:i0 + 30000] if i0 >= 0 else html
            imgs = list(dict.fromkeys(re.findall(r'"hiRes":"(https:[^"]+)"', seg)))
            bl = re.search(r'id="feature-bullets"(.*?)</ul>', html, re.S)
            bullets = [ap.clean(x) for x in re.findall(r"<li[^>]*>(.*?)</li>", bl.group(1), re.S)] if bl else []
            text = ap.clean(html)
            by = re.search(r'id="bylineInfo"[^>]*>(.*?)</a>', html, re.S)
            rate = re.search(r"(\d\.\d) out of 5 stars", text)
            cnt = re.search(r"([\d,]+) (?:global )?ratings", text)
            rec.update({"title": ap.title_of(html), "byline": ap.clean(by.group(1)) if by else None, "pageAsin": pg.get("asin"),
                        "error": pg.get("error"), "aed": pg.get("aed"), "days": pg.get("sourceDays"), "inStock": pg.get("inStock"),
                        "stockLeft": pg.get("stockLeft"), "seller": pg.get("seller"), "delivery": pg.get("deliveryText"),
                        "rating": rate.group(1) if rate else None, "nratings": cnt.group(1) if cnt else None,
                        "images": imgs[:3], "bullets": [b[:160] for b in bullets[:5]], "mentions": snippets(text)})
        except Exception as e:  # noqa: BLE001
            rec["exception"] = f"{type(e).__name__}: {e}"[:120]
        print("NP", json.dumps(rec, ensure_ascii=False), flush=True)
        time.sleep(6 + random.uniform(0, 3))


if __name__ == "__main__":
    main()
