#!/usr/bin/env python3
"""Reads the IDENTITY of every Amazon.ae product page of the shop (read-only: nothing is changed on Shopify).

For each ASIN of the shop (same list as amazon_sync.py): page ASIN after redirects, title, selected variation
labels, size / pack markers, availability text. Result: out/identity-<shard>.jsonl, plus the raw pages (gzip).
Used to compare what the shop sells with what the Amazon.ae page really is (shade names, sizes, packs).
Env: SHOPIFY_* (to list the ASINs), SHARD=i/n, DELAY, ONLY_ASINS (comma separated), OUT_DIR.
"""
import gzip
import json
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import amazon_sync as a  # noqa: E402
import browser_fetch as b  # noqa: E402


def text(x):
    return re.sub(r"<[^>]+>|\s+", " ", x or "").strip()


def first(rx, html, flags=re.S):
    m = re.search(rx, html, flags)
    return text(m.group(1)) if m else None


def block(html, element_id, size=900):
    i = html.find(f'id="{element_id}"')
    return text(html[i:i + size])[:size // 2] if i >= 0 else None


def identity(html, asin):
    out = {"asin": asin, "bytes": len(html)}
    out["canonical"] = first(r'<link rel="canonical" href="([^"]+)"', html)
    out["input_asin"] = first(r'<input[^>]*\bid="ASIN"[^>]*value="([^"]*)"', html)
    out["parent_asin"] = first(r'"parentAsin"\s*:\s*"([^"]*)"', html)
    out["title"] = first(r'id="productTitle"[^>]*>(.*?)</span>', html)
    out["brand_line"] = first(r'id="bylineInfo"[^>]*>(.*?)</a>', html)
    out["selected_variations"] = first(r'"selected_variations"\s*:\s*(\{[^}]*\})', html)
    sel = {}
    for m in re.finditer(r'id="(variation_[a-z_]+|inline-twister-expanded-dimension-text-[a-z_]+)"', html):
        sel[m.group(1)] = text(html[m.end():m.end() + 400])[:100]
    out["twister"] = sel
    out["variation_family"] = first(r'"variationValues"\s*:\s*(\{.{0,600}?\})', html)
    out["bullets"] = block(html, "feature-bullets", 2400)
    out["overview"] = block(html, "productOverview_feature_div", 1600)
    out["tech"] = block(html, "productDetails_techSpec_section_1", 1600)
    out["details"] = block(html, "detailBullets_feature_div", 1600)
    out["availability"] = block(html, "availability", 400)
    out["not_found"] = ("Page Not Found" in html) or ("dogsofamazon" in html)
    return out


def main():
    outdir = os.environ.get("OUT_DIR", "out")
    os.makedirs(os.path.join(outdir, "pages"), exist_ok=True)
    asins = sorted({r["asin"] for r in a.load_variants()})
    if os.environ.get("ONLY_ASINS"):
        wanted = set(os.environ["ONLY_ASINS"].split(","))
        asins = [x for x in asins if x in wanted]
    shard = os.environ.get("SHARD", "0/1")
    i, n = (int(x) for x in shard.split("/"))
    asins = asins[i::n]
    delay = float(os.environ.get("DELAY", "8"))
    print(f"{len(asins)} pages to read (shard {shard})", flush=True)
    time.sleep(random.uniform(0, 60))
    done = errors = 0
    path = os.path.join(outdir, f"identity-{i}of{n}.jsonl")
    reader = None
    with open(path, "a", encoding="utf-8") as fh:
        for k, asin in enumerate(asins, 1):
            if reader is None:
                for attempt in range(1, 4):
                    reader = b.BrowserReader()
                    try:
                        reader.start()
                        break
                    except (b.LocationLost, b.Captcha) as e:
                        reader.close()
                        reader = None
                        print(f"start failed ({e}), try {attempt}", flush=True)
                        time.sleep(45 + random.uniform(0, 30))
                if reader is None:
                    sys.exit("could not start the browser with a Dubai address")
            try:
                html = reader.get(f"https://www.amazon.ae/dp/{asin}?language=en_AE")
                rec = identity(html, asin)
                rec["url"] = reader.page.url[:200]
                rec["status"] = getattr(reader, "last_status", None)
                with gzip.open(os.path.join(outdir, "pages", f"{asin}.html.gz"), "wt", encoding="utf-8") as g:
                    g.write(html)
                done += 1
            except Exception as e:
                rec = {"asin": asin, "error": f"{type(e).__name__}: {e}"[:200]}
                errors += 1
                if isinstance(e, (b.LocationLost, b.Captcha)):  # restart the browser, pause
                    reader.close()
                    reader = None
                    time.sleep(60 + random.uniform(0, 60))
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if k % 10 == 0:
                print(f"{k}/{len(asins)} read, {errors} errors", flush=True)
            time.sleep(delay + random.uniform(0, delay / 2))
    if reader:
        reader.close()
    print(f"done: {done} read, {errors} errors")


if __name__ == "__main__":
    main()
