#!/usr/bin/env python3
"""Stops selling variants the stock sync cannot check.

amazon_sync.py reads a variant only if it has an ASIN (SKU "B0…" / "AMZ-B0…", or the product's ASIN metafield when
the product has a single variant). A variant of a multi-variant product with no ASIN of its own is never read, so it
stayed on sale whatever Amazon.ae said (e.g. a shade that is not sold on Amazon.ae). This script sets those variants
to "Épuisé" (inventoryPolicy DENY) and lists them, so the missing ASIN can be added to the SKU.

Usage: python3 -I unmapped_guard.py   (same environment as amazon_sync.py; DRY_RUN=1 reports only)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I does not add the script folder
import amazon_sync as s  # noqa: E402

MAX_FLIPS = 150  # more than this at once = something is off with the data: report only

Q = """query($after:String){ products(first:50, after:$after, query:"status:active"){
  pageInfo{hasNextPage endCursor}
  nodes{ id handle
    ref: metafield(namespace:"internal", key:"supplier_ref"){value}
    spreadr: metafield(namespace:"global", key:"spreadr-asin"){value}
    variants(first:100){ nodes{ id title sku inventoryPolicy } } } } }"""


def main():
    if not (os.environ.get("SHOPIFY_STORE") and (os.environ.get("SHOPIFY_TOKEN") or os.environ.get("SHOPIFY_CLIENT_SECRET"))):
        print("No Shopify credentials set: nothing to do.")
        return
    dry = os.environ.get("DRY_RUN") == "1"
    todo, no_asin_single, after = {}, [], None
    while True:
        data = s.gql(Q, {"after": after})["products"]
        for p in data["nodes"]:
            variants = p["variants"]["nodes"]
            product_asin = None
            for src in (p.get("spreadr"), p.get("ref")):
                m = src and s.ASIN_RE.search(src["value"])
                if m:
                    product_asin = m.group(1)
                    break
            for v in variants:
                if s.ASIN_RE.search(v.get("sku") or ""):
                    continue
                if len(variants) == 1:
                    if not product_asin:
                        no_asin_single.append(p["handle"])
                    continue
                if v["inventoryPolicy"] == "CONTINUE":
                    todo.setdefault(p["id"], []).append({"id": v["id"], "inventoryPolicy": "DENY",
                                                         "_label": f"{p['handle']} / {v['title']}"})
        if not data["pageInfo"]["hasNextPage"]:
            break
        after = data["pageInfo"]["endCursor"]
    n = sum(len(v) for v in todo.values())
    print(f"{n} variants of multi-variant products have no ASIN and are on sale; "
          f"{len(no_asin_single)} single-variant products have no ASIN at all (not read, left as is).")
    for ups in todo.values():
        for u in ups:
            print("  no ASIN:", u["_label"])
    for h in no_asin_single[:40]:
        print("  single variant, no ASIN:", h)
    if dry or n == 0:
        return
    if n > MAX_FLIPS:
        print(f"More than {MAX_FLIPS} variants: not changed, to be checked by hand.")
        return
    errors = 0
    for pid, ups in todo.items():
        res = s.gql(s.PRICES_M, {"p": pid, "v": [{"id": u["id"], "inventoryPolicy": "DENY"} for u in ups]})
        errs = res["productVariantsBulkUpdate"]["userErrors"]
        errors += len(errs)
        for e in errs:
            print("error:", pid, e)
    print(f"{n} variants set to Épuisé, {errors} Shopify errors.")


if __name__ == "__main__":
    main()
