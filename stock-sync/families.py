#!/usr/bin/env python3
"""Read-only: for each seed ASIN (stock-sync/seeds.txt, a contiguous chunk per shard) reads the Amazon.ae page (Dubai
address) and writes the whole shade/size family it belongs to (dimensionValuesDisplayData), the colour -> ASIN map,
one photo per colour and the facts of the seed itself. Seeds already covered by a family read earlier in the shard are skipped.
Usage: python3 -I families.py SHARD NSHARDS outdir        Changes nothing anywhere.
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


def jsonat(html, key):
    """The JSON value that follows "key": in the page, or None."""
    m = re.search(r'"%s"\s*:\s*' % re.escape(key), html)
    if not m:
        return None
    try:
        return json.JSONDecoder().raw_decode(html[m.end():])[0]
    except ValueError:
        return None


def facts(html, asin):
    out = {"seed": asin}
    out["dvdd"] = jsonat(html, "dimensionValuesDisplayData") or {}
    out["dims"] = jsonat(html, "dimensions") or []
    ci = jsonat(html, "colorImages")
    out["images"] = {k: (v[0].get("hiRes") or v[0].get("large")) for k, v in (ci or {}).items()
                     if isinstance(v, list) and v and isinstance(v[0], dict)} if isinstance(ci, dict) else {}
    out["colorToAsin"] = {k: (v or {}).get("asin") for k, v in (jsonat(html, "colorToAsin") or {}).items()}
    m = re.search(r'id="bylineInfo"[^>]*>(.*?)</a>', html, re.S)
    out["byline"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else None
    m = re.search(r'"parentAsin"\s*:\s*"([^"]*)"', html)
    out["parent"] = m.group(1) if m else None
    return out


def main():
    shard, n, outdir = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    seeds = [x.strip() for x in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds.txt")) if x.strip()]
    size = -(-len(seeds) // n)
    mine = seeds[shard * size:(shard + 1) * size]
    os.makedirs(outdir, exist_ok=True)
    out = open(os.path.join(outdir, f"families-{shard}.jsonl"), "w", encoding="utf-8")
    delay = float(os.environ.get("DELAY", "7"))
    a.start_browser()
    covered, read = set(), 0
    print(f"shard {shard}/{n}: {len(mine)} seeds", flush=True)
    for i, asin in enumerate(mine, 1):
        if asin in covered:
            continue
        today = dt.datetime.now(dt.timezone(dt.timedelta(hours=4))).date()
        try:
            html = a.fetch(asin)
            pg = a.choose_offer(a.parse(html, today, asin))
            rec = facts(html, asin)
        except Exception as e:  # noqa: BLE001
            print("ERR", asin, f"{type(e).__name__}: {e}"[:100], flush=True)
            continue
        read += 1
        rec.update({"title": pg.get("title"), "shade": pg.get("variation"), "aed": pg.get("aed"), "inStock": pg.get("inStock"),
                    "days": pg.get("sourceDays"), "seller": pg.get("seller"), "error": pg.get("error"), "gone": pg.get("gone", False),
                    "pageAsin": pg.get("asin"), "stockLeft": pg.get("stockLeft")})
        covered |= set(rec["dvdd"]) | {asin}
        line = json.dumps(rec, ensure_ascii=False)
        out.write(line + "\n")
        out.flush()
        print(f"[{i}/{len(mine)}] ROW {asin} family {len(rec['dvdd'])} {(rec['title'] or '')[:60]}", flush=True)
        time.sleep(delay + random.uniform(0, delay / 2))
    out.close()
    print(f"read {read} of {len(mine)}", flush=True)


if __name__ == "__main__":
    main()
