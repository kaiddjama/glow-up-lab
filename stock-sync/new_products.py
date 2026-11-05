#!/usr/bin/env python3
"""Lists the ASINs of new products hidden because they were never read on Amazon.ae (see park_soldout.py), so they can
be read right away (amazon_sync.py with ONLY_ASINS) and put online within 30 minutes if they are sellable.

Only products created in the last DAYS days are listed, so a product that stays unsellable is not read every 30 min
forever (the five daily full checks keep reading it). Writes count= and asins= to $GITHUB_OUTPUT.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I does not add the script folder
import amazon_sync as s  # noqa: E402

DAYS = 3
Q = """query($after:String,$q:String!){ products(first:100, after:$after, query:$q){
  pageInfo{hasNextPage endCursor}
  nodes{ handle chk: metafield(namespace:"supplier", key:"checked_at"){value}
    ref: metafield(namespace:"internal", key:"supplier_ref"){value}
    variants(first:100){ nodes{ sku } } } } }"""


def main():
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    asins, after = [], None
    while True:
        data = s.gql(Q, {"after": after, "q": f"status:draft tag:{s.OUT_TAG} created_at:>'{since}'"})["products"]
        for p in data["nodes"]:
            if p.get("chk"):
                continue
            vs = p["variants"]["nodes"]
            found = [m.group(1) for v in vs for m in [s.ASIN_RE.search(v.get("sku") or "")] if m]
            if not found and len(vs) == 1 and p.get("ref"):
                m = s.ASIN_RE.search(p["ref"]["value"])
                found = [m.group(1)] if m else []
            if found:
                print("new product to read:", p["handle"], found)
            asins += found
        if not data["pageInfo"]["hasNextPage"]:
            break
        after = data["pageInfo"]["endCursor"]
    asins = sorted(set(asins))[:60]
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"count={len(asins)}\nasins={','.join(asins)}\n")
    print(f"{len(asins)} pages of new products to read")


if __name__ == "__main__":
    main()
