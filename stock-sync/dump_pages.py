#!/usr/bin/env python3
"""Read-only: saves the raw HTML (gzip) of the listed Amazon.ae pages (Dubai address). Usage: python3 -I dump_pages.py outdir ASIN..."""
import gzip
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import amazon_sync as a  # noqa: E402

os.makedirs(sys.argv[1], exist_ok=True)
a.start_browser()
for asin in sys.argv[2:]:
    html = a.fetch(asin)
    with gzip.open(os.path.join(sys.argv[1], f"{asin}.html.gz"), "wt", encoding="utf-8") as f:
        f.write(html)
    print(asin, len(html), flush=True)
    time.sleep(6 + random.uniform(0, 3))
