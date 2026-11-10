#!/usr/bin/env python3
"""Second source in use: keeps an eye, every 10 minutes, on the variants the stock sync sells from their second source.

A variant whose SKU is an Amazon.ae ASIN may carry the metafield supplier.fallback = "PSAE-<handle>" or "MEDX-<alias>"
(Hoodo, 10 Nov: "si ils tombent en rupture padelshop est le second choix"). When Amazon.ae cannot sell it and that source
can, amazon_sync.py keeps it on sale at that source's price, remembers it in supplier.sync_state ("src", "src_t") and tags
the product "source-2". Amazon.ae is read five times a day; a second source in use must be confirmed more often. So here:
  - the source still sells it: price refreshed (same guard as everywhere), "src_t" and the "verified" stamp renewed;
  - it no longer does, or the reference was removed or changed: Épuisé at once (the next full check decides again);
  - its page cannot be read: left as it is until the source's own limit (MEDX_STALE_HOURS, PADELSHOP_STALE_HOURS), then Épuisé.
Putting back on sale and going back to Amazon.ae are the full check's job, never this script's.
Usage: python3 -I fallback_sync.py   (same settings as amazon_sync.py; DRY_RUN=1 reports only)
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I does not add the script folder
import amazon_sync as s  # noqa: E402
import suppliers  # noqa: E402


def decide(r, page, mod, now):
    """Pure. ("keep" | "refresh" | "stop", price to set or None, new state) for a variant sold from its second source."""
    state = dict(r["state"])
    off = {k: v for k, v in state.items() if k not in ("src", "src_t")}
    if r["policy"] != "CONTINUE":
        return "stop", None, off  # hidden by another control: no longer "sold from the second source"
    if not mod or r["fallback"] != state.get("src"):
        return "stop", None, off
    if page.get("error"):
        return ("stop", None, off) if s.hours_since(state.get("src_t"), now) > mod.STALE_HOURS else ("keep", None, state)
    if not mod.sellable(page, True):
        return "stop", None, off
    price, new = None, s.formula(page["aed"], r["grams"])
    if abs(new - r["price"]) >= 50:
        price, hold, state = s.guard_price(r["price"], new, page["aed"], state, now)
        if hold == "rise":
            return "stop", None, {**off, "pend": state["pend"]}
    else:
        state.pop("pend", None)
    return "refresh", price, {**state, "src_t": s.iso(now)}


def main():
    if not s.have_credentials():
        return
    if not s.AED_TO_FDJ:
        sys.exit("ALERTE: PRICE_FORMULA is not set: no price can be computed, nothing changed.")
    dry = os.environ.get("DRY_RUN") == "1"
    now = dt.datetime.now(dt.timezone.utc)
    rows = s.load_rows(f"status:active tag:{s.SECOND_SOURCE_TAG}", False)
    using = [r for r in rows if r["state"].get("src")]
    idle = {r["productId"] for r in rows} - {r["productId"] for r in using}
    print(f"{len(using)} variants sold from their second source, {len(idle)} products carrying the tag for nothing.")
    pages, by_product, fields, stopped = {}, {}, [], 0
    for r in using:
        mod, slug, name = suppliers.module_of(r["state"]["src"])
        if mod and r["state"]["src"] not in pages:
            pages[r["state"]["src"]] = mod.fetch(slug)
        what, price, state = decide(r, pages.get(r["state"]["src"], {}), mod, now)
        print(f"  {r['handle']} / {r['variant']} ({r['state']['src']}): {what}" + (f", price {price}" if price else ""))
        if what == "keep":
            continue
        upd = {"id": r["variantId"]}
        if what == "stop":
            stopped += 1
            if r["policy"] == "CONTINUE":
                upd["inventoryPolicy"] = "DENY"
        elif price is not None:
            upd["price"] = str(price)
        if len(upd) > 1:
            by_product.setdefault(r["productId"], []).append(upd)
        fields.append(s.field(r["variantId"], "sync_state", "json", json.dumps(state, separators=(",", ":"))))
        if what == "refresh":
            fields.append(s.field(r["variantId"], "variant_checked_at", "date_time", s.iso(now)))
    if dry:
        return
    errors = 0
    for pid, ups in by_product.items():
        errs = s.gql(s.PRICES_M, {"p": pid, "v": ups})["productVariantsBulkUpdate"]["userErrors"]
        errors += len(errs)
        for e in errs:
            print("error:", pid, e)
    for i in range(0, len(fields), 25):
        errors += len(s.gql(s.META_M, {"m": fields[i:i + 25]})["metafieldsSet"]["userErrors"])
    for pid in idle:
        errors += len(s.gql(s.TAGS_REMOVE_M, {"id": pid, "t": [s.SECOND_SOURCE_TAG]})["tagsRemove"]["userErrors"])
    print(f"{stopped} variants no longer sold from their second source, {errors} Shopify errors.")
    if errors:
        sys.exit(f"ALERTE: {errors} Shopify errors.")


if __name__ == "__main__":
    main()
