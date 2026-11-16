#!/usr/bin/env python3
"""Read-only: saves the raw HTML (gzip) of the listed Amazon.ae pages (Dubai address) and prints, for each page, one
"SUMMARY {json}" line in the log: title, seller of the featured offer, product rating and rating count, seller profile id,
and the review snippets of the page that talk about fakes. Usage: python3 -I dump_pages.py outdir ASIN..."""
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

FAKE_RE = re.compile(r"fake|counterfeit|not original|not authentic|not genuine|knock[- ]?off|imitation|scam|"
                     r"tamper|expired|used before|already used|watered|different from|not as described|"
                     r"مقلد|مزيف|غير اصلي|غير أصلي|تقليد|مغشوش", re.I)


def summary(asin, html):
    out = {"asin": asin, "bytes": len(html)}
    try:
        out["title"] = (ap.title_of(html) or "")[:90]
        segs = ap.buybox_offers(html)
        out["sellers"] = [ap.parse_seller(s) for s in segs][:4]
        ship = ap._feature(segs[0], "fulfillerInfoFeature") if segs else ("", "")
        out["fulfilled"] = " ".join(ship).strip()[:60]
        m = re.search(r'id="acrPopover"[^>]*title="([^"]+)"', html) or re.search(r'([\d.]+) out of 5 stars', html)
        out["rating"] = m.group(1) if m else None
        m = re.search(r'id="acrCustomerReviewText"[^>]*>\s*\(?([\d,.KkMm]+)', html)
        out["ratings_count"] = m.group(1) if m else None
        m = re.search(r'seller=([A-Z0-9]{8,16})', html)
        out["seller_id"] = m.group(1) if m else None
        bodies = [ap.clean(b) for b in re.findall(r'data-hook="review-body"[^>]*>(.*?)</div>\s*</div>', html, re.S)]
        out["reviews_on_page"] = len(bodies)
        out["fake_mentions"] = [b[:200] for b in bodies if FAKE_RE.search(b)][:5]
        out["brand_line"] = ap.clean((re.search(r'id="bylineInfo"[^>]*>(.*?)</a>', html, re.S) or [None, ""])[1])[:60]
    except Exception as e:  # never stop the dump because of the summary
        out["summary_error"] = str(e)[:120]
    return out


os.makedirs(sys.argv[1], exist_ok=True)
a.start_browser()
for asin in sys.argv[2:]:
    html = a.fetch(asin)
    with gzip.open(os.path.join(sys.argv[1], f"{asin}.html.gz"), "wt", encoding="utf-8") as f:
        f.write(html)
    print(asin, len(html), flush=True)
    print("SUMMARY " + json.dumps(summary(asin, html), ensure_ascii=False), flush=True)
    time.sleep(6 + random.uniform(0, 3))
