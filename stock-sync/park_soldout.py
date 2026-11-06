#!/usr/bin/env python3
"""Hides the products that are entirely sold out, and brings them back when one variant can be sold again.

amazon_sync.py only sets single variants to Épuisé (inventoryPolicy DENY). A product whose variants are ALL Épuisé
stayed published, with every option struck through (e.g. Tree Hut whipped butter). This script runs after the sync:
  - ACTIVE product, every variant DENY  -> DRAFT + tag OUT_TAG ("epuise-auto");
  - DRAFT product carrying OUT_TAG with at least one variant sellable (CONTINUE) -> ACTIVE, tag removed.
Also hidden: ACTIVE products never read on Amazon.ae (no supplier.checked_at) that have a variant on sale, so a new
product cannot be sold before its stock and delivery date were read; the next sync reads it (it is loaded as a hidden
product) and puts it online if it is sellable. Only products carrying OUT_TAG are ever brought back, so products hidden by hand or by another process are not touched.
Products whose variants have no ASIN stay hidden (nothing can verify them): they are listed so the ASIN can be added.

Usage: python3 -I park_soldout.py   (same environment as amazon_sync.py; DRY_RUN=1 reports only)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I does not add the script folder
import amazon_sync as s  # noqa: E402

GUARD_ONLY = os.environ.get("GUARD_ONLY") == "1"  # frequent run: only hide the never-verified products
MAX_SHARE = 0.60  # more than this share of the active catalogue at once = something is off: report only

PUBLICATION = os.environ.get("ONLINE_STORE_PUBLICATION", "gid://shopify/Publication/338148819125")  # Online Store channel
PUBLISH_M = """mutation($id:ID!,$p:ID!){publishablePublish(id:$id, input:[{publicationId:$p}]){userErrors{field message}}}"""
Q = """query($after:String,$q:String!,$pub:ID!){ products(first:100, after:$after, query:$q){
  pageInfo{hasNextPage endCursor}
  nodes{ id handle tags isGiftCard
    pub: publishedOnPublication(publicationId:$pub)
    chk: metafield(namespace:"supplier", key:"checked_at"){value}
    ref: metafield(namespace:"internal", key:"supplier_ref"){value}
    variants(first:100){ nodes{ sku inventoryPolicy } } } } }"""


def load(search):
    out, after = [], None
    while True:
        data = s.gql(Q, {"after": after, "q": search, "pub": PUBLICATION})["products"]
        out += [p for p in data["nodes"] if not p.get("isGiftCard")]  # gift cards have no Amazon.ae page: never hidden by this script
        if not data["pageInfo"]["hasNextPage"]:
            return out
        after = data["pageInfo"]["endCursor"]


def all_out(p):
    vs = p["variants"]["nodes"]
    return bool(vs) and all(v["inventoryPolicy"] == "DENY" for v in vs)


def main():
    if not (os.environ.get("SHOPIFY_STORE") and (os.environ.get("SHOPIFY_TOKEN") or os.environ.get("SHOPIFY_CLIENT_SECRET"))):
        print("No Shopify credentials set: nothing to do.")
        return
    dry = os.environ.get("DRY_RUN") == "1"
    active = load("status:active")
    parked = load(f"status:draft tag:{s.OUT_TAG}")
    # never verified on Amazon.ae (no supplier.checked_at) and on sale = published before its stock was read: hidden
    unverified = [p for p in active if not p.get("chk") and not all_out(p)]
    to_hide = unverified if GUARD_ONLY else [p for p in active if all_out(p) or p in unverified]
    to_show = [p for p in parked if not all_out(p) and p.get("chk")]
    # ACTIVE, read on Amazon.ae, sellable, but not published on the Online Store: the page answers 404 (Owala, 5 Nov)
    to_publish = [p for p in active if p.get("chk") and not all_out(p) and not p.get("pub")]
    to_publish += [p for p in to_show if not p.get("pub")]
    unmapped = [p for p in to_hide if not any(s.ASIN_RE.search(v.get("sku") or "") for v in p["variants"]["nodes"])
                and not (len(p["variants"]["nodes"]) == 1 and p.get("ref") and s.ASIN_RE.search(p["ref"]["value"]))]
    print(f"{len(active)} active products: {len(to_hide)} entirely sold out to hide "
          f"({len(unmapped)} of them with no ASIN to verify them); {len(parked)} hidden by this script, "
          f"{len(to_show)} to bring back.")
    for p in to_hide:
        print("  hide:", p["handle"], "(no ASIN)" if p in unmapped else "")
    for p in to_show:
        print("  show again:", p["handle"])
    print(f"{len(to_publish)} sellable products not published on the Online Store (page in 404) to publish")
    for p in to_publish:
        print("  publish:", p["handle"])
    if dry:
        return
    if active and len(to_hide) > MAX_SHARE * len(active):
        sys.exit(f"{len(to_hide)} of {len(active)} products would be hidden: not changed, to be checked by hand.")
    errors = 0
    for p, status in [(p, "DRAFT") for p in to_hide] + [(p, "ACTIVE") for p in to_show]:
        calls = [(s.STATUS_M, {"p": {"id": p["id"], "status": status}}),
                 ((s.TAGS_ADD_M if status == "DRAFT" else s.TAGS_REMOVE_M), {"id": p["id"], "t": [s.OUT_TAG]})]
        for q, vars_ in calls:
            errs = next(iter(s.gql(q, vars_).values()))["userErrors"]
            errors += len(errs)
            for e in errs:
                print("error:", p["handle"], e)
    for p in to_publish:
        errs = s.gql(PUBLISH_M, {"id": p["id"], "p": PUBLICATION})["publishablePublish"]["userErrors"]
        errors += len(errs)
        for e in errs:
            print("publish error:", p["handle"], e)
    print(f"{len(to_hide)} hidden, {len(to_show)} back online, {len(to_publish)} published, {errors} Shopify errors.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
