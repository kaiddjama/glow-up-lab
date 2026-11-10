#!/usr/bin/env python3
"""Checks that every variant on sale was verified on Amazon.ae by the latest sync, and never leaves one unverified.

A variant on sale ("continue selling") counts as verified when its Amazon.ae page was read in the last STALE_HOURS
(metafield supplier.variant_checked_at, written by amazon_sync.py). Variants without an ASIN can never be verified.

  python3 -I coverage.py list     prints the ASINs still to read (also to $GITHUB_OUTPUT: count, asins)
  python3 -I coverage.py enforce  sets the variants still unverified to Épuisé (DRY_RUN=1: only reports). If too many
                                  are unverified (page reading probably broke), it changes nothing and exits 1.
  python3 -I coverage.py medx     same for the MedX variants (SKU "MEDX-..."), which medx_sync.py reads every 30 min: any
                                  not read for MEDX_STALE_HOURS (3) hours is set to Épuisé, whatever their number, because
                                  stock that cannot be confirmed is never sold. Exits 1 (alert) when some were hidden.
  The Amazon.ae modes ignore the MedX variants.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I does not add the script folder
import amazon_sync as s  # noqa: E402
import medx  # noqa: E402

STALE_HOURS = 6  # three checks a day, about 7 hours apart
MAX_SHARE = 0.10  # more unverified than this = reading is broken, not a few bad pages: alert instead of hiding
MAX_RETRY = 300  # ASINs re-read per retry pass (about an hour at one page every 10 s)

Q = """query($after:String){ products(first:50, after:$after, query:"status:active"){
  pageInfo{hasNextPage endCursor}
  nodes{ id handle isGiftCard
    ref: metafield(namespace:"internal", key:"supplier_ref"){value}
    spreadr: metafield(namespace:"global", key:"spreadr-asin"){value}
    variants(first:100){ nodes{ id title sku inventoryPolicy
      checked: metafield(namespace:"supplier", key:"variant_checked_at"){value} } } } } }"""


def unverified(medx_mode=False):
    """(on-sale variant count, [unverified variants]) among active products: the Amazon.ae variants, or with
    medx_mode the MedX ones (SKU "MEDX-...", read by medx_sync.py, stale after medx.STALE_HOURS)."""
    limit = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=medx.STALE_HOURS if medx_mode else STALE_HOURS)
    on_sale, bad, after = 0, [], None
    while True:
        data = s.gql(Q, {"after": after})["products"]
        for p in data["nodes"]:
            if p.get("isGiftCard"):  # gift card: no Amazon.ae page to verify
                continue
            variants = p["variants"]["nodes"]
            product_asin = None
            for src in (p.get("spreadr"), p.get("ref")):
                m = src and s.ASIN_RE.search(src["value"])
                if m:
                    product_asin = m.group(1)
                    break
            for v in variants:
                if v["inventoryPolicy"] != "CONTINUE":
                    continue
                if bool(medx.slug_of(v.get("sku"))) != medx_mode:
                    continue
                on_sale += 1
                m = s.ASIN_RE.search(v.get("sku") or "")
                asin = m.group(1) if m else (product_asin if len(variants) == 1 else None)
                seen = (v.get("checked") or {}).get("value")
                fresh = bool(seen) and dt.datetime.fromisoformat(seen.replace("Z", "+00:00")) >= limit
                if not fresh or not (asin or medx_mode):
                    bad.append({"product": p["id"], "variant": v["id"], "asin": asin,
                                "label": f"{p['handle']} / {v['title']}", "seen": seen})
        if not data["pageInfo"]["hasNextPage"]:
            return on_sale, bad
        after = data["pageInfo"]["endCursor"]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "list"
    if not (os.environ.get("SHOPIFY_STORE") and (os.environ.get("SHOPIFY_TOKEN") or os.environ.get("SHOPIFY_CLIENT_SECRET"))):
        print("No Shopify credentials set: nothing to do.")
        return
    if mode == "medx":
        on_sale, bad = unverified(True)
        print(f"{len(bad)} of {on_sale} MedX variants on sale were not read in the last {medx.STALE_HOURS} h.")
    else:
        on_sale, bad = unverified()
        print(f"{len(bad)} of {on_sale} variants on sale are not verified (no ASIN, or page not read in the last {STALE_HOURS} h).")
    if mode == "list":
        asins = sorted({b["asin"] for b in bad if b["asin"]})[:MAX_RETRY]
        print(f"{len(asins)} ASINs to read again.")
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a") as f:
                f.write(f"count={len(asins)}\nasins={','.join(asins)}\n")
        return
    for b in bad[:60]:
        print("  not verified:", b["label"], "| ASIN:", b["asin"], "| last read:", b["seen"])
    if not bad:
        return
    if mode != "medx" and len(bad) > max(25, MAX_SHARE * on_sale):
        print(f"Too many unverified variants ({len(bad)}): reading is probably broken, nothing hidden. Check the logs.")
        sys.exit(1)
    if os.environ.get("DRY_RUN") == "1":
        return
    by_product, errors = {}, 0
    for b in bad:
        by_product.setdefault(b["product"], []).append({"id": b["variant"], "inventoryPolicy": "DENY"})
    for pid, ups in by_product.items():
        errs = s.gql(s.PRICES_M, {"p": pid, "v": ups})["productVariantsBulkUpdate"]["userErrors"]
        errors += len(errs)
        for e in errs:
            print("error:", pid, e)
    print(f"{len(bad)} unverified variants set to Épuisé, {errors} Shopify errors.")
    if mode == "medx":
        sys.exit(f"ALERTE: {len(bad)} MedX variants had not been read for {medx.STALE_HOURS} h and were set to Épuisé.")


if __name__ == "__main__":
    main()
