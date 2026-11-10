#!/usr/bin/env python3
"""Checks that every variant on sale was verified on Amazon.ae by the latest sync, and never leaves one unverified.

A variant on sale ("continue selling") counts as verified when its Amazon.ae page was read in the last STALE_HOURS
(metafield supplier.variant_checked_at, written by amazon_sync.py). Variants without an ASIN can never be verified.

  python3 -I coverage.py list     prints the ASINs still to read (also to $GITHUB_OUTPUT: count, asins). With
                                  RUN_STARTED_AT (the start of the current check) it lists everything on sale that THIS
                                  check did not read, not only what is 6 h old: a reader that stopped or tripped its guard
                                  is made up for at once instead of at the next check.
  python3 -I coverage.py enforce  sets the variants still unverified to Épuisé (DRY_RUN=1: only reports).
                                  - no ASIN: always (they cannot be verified), unless there are more than MAX_UNMAPPED;
                                  - not read for STALE_HOURS: yes, unless they are more than MAX_SHARE of what is on sale
                                    (the reading is probably broken: alert, exit 1);
                                  - not read for HARD_STALE_HOURS: always, whatever their number (stock that cannot be
                                    confirmed for half a day is not sold). HARD_STALE_HOURS=0 turns this limit off.
                                  Exits 1 (alert) too when this check left more than MAX_SHARE of the variants unread.
  python3 -I coverage.py medx     same for the MedX variants (SKU "MEDX-..."), which medx_sync.py reads every 10 min: any
                                  not read for MEDX_STALE_HOURS (1) hour is set to Épuisé, whatever their number, because
                                  stock that cannot be confirmed is never sold. Exits 1 (alert) when some were hidden.
  python3 -I coverage.py padelshop  same for the PadelShop.ae variants (SKU "PSAE-..."), read by padelshop_sync.py every 30 min,
                                  stale after PADELSHOP_STALE_HOURS (3) hours.
  The Amazon.ae modes ignore the MedX and PadelShop.ae variants. A variant sold from its second source (supplier.fallback)
  is stamped by fallback_sync.py, which also hides it when that source cannot be read in time.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I does not add the script folder
import amazon_sync as s  # noqa: E402
import medx  # noqa: E402
import padelshop  # noqa: E402

STALE_HOURS = 6  # five checks a day, about 5 hours apart
HARD_STALE_HOURS = float(os.environ.get("HARD_STALE_HOURS", "12"))  # unread for this long = Épuisé whatever the number
MAX_SHARE = 0.10  # more unverified than this = reading is broken, not a few bad pages: alert
MAX_RETRY = 300  # ASINs re-read per retry pass (about an hour at one page every 10 s)
MAX_UNMAPPED = 150  # more variants without an ASIN than this at once = a data problem: alert only (as unmapped_guard.py)

Q = """query($after:String){ products(first:50, after:$after, query:"status:active"){
  pageInfo{hasNextPage endCursor}
  nodes{ id handle isGiftCard variantsCount{ count }
    ref: metafield(namespace:"internal", key:"supplier_ref"){value}
    spreadr: metafield(namespace:"global", key:"spreadr-asin"){value}
    variants(first:100){ nodes{ id title sku inventoryPolicy
      checked: metafield(namespace:"supplier", key:"variant_checked_at"){value} } } } } }"""


def on_sale(kind="amazon", now=None):
    """The variants on sale of active products read by one source ("amazon", "medx", "shop"): product, variant, asin, label,
    seen (text of the last reading) and age (hours since it; None = never read)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    out, after = [], None
    while True:
        data = s.gql(Q, {"after": after})["products"]
        for p in data["nodes"]:
            if p.get("isGiftCard"):  # gift card: no Amazon.ae page to verify
                continue
            variants = p["variants"]["nodes"]
            total = ((p.get("variantsCount") or {}).get("count")) or len(variants)
            product_asin = None
            for src in (p.get("spreadr"), p.get("ref")):
                m = src and s.ASIN_RE.search(src["value"])
                if m:
                    product_asin = m.group(1)
                    break
            for v in variants:
                if v["inventoryPolicy"] != "CONTINUE":
                    continue
                mine = "medx" if medx.slug_of(v.get("sku")) else "shop" if padelshop.slug_of(v.get("sku")) else "amazon"
                if mine != kind:
                    continue
                m = s.ASIN_RE.search(v.get("sku") or "")
                seen = (v.get("checked") or {}).get("value")
                age = s.hours_since(seen, now) if seen else None
                out.append({"product": p["id"], "variant": v["id"], "label": f"{p['handle']} / {v['title']}",
                            "asin": m.group(1) if m else (product_asin if total == 1 else None), "seen": seen,
                            "age": None if age is None or age > 1e8 else age})
        if not data["pageInfo"]["hasNextPage"]:
            return out
        after = data["pageInfo"]["endCursor"]


def older(v, hours):
    return v["age"] is None or v["age"] > hours


def hide(bad):
    """Épuisé for these variants. Returns the number of Shopify errors."""
    by_product, errors = {}, 0
    for b in bad:
        by_product.setdefault(b["product"], []).append({"id": b["variant"], "inventoryPolicy": "DENY"})
    for pid, ups in by_product.items():
        errs = s.gql(s.PRICES_M, {"p": pid, "v": ups})["productVariantsBulkUpdate"]["userErrors"]
        errors += len(errs)
        for e in errs:
            print("error:", pid, e)
    return errors


def decide(variants, since_hours=None):
    """What "enforce" does with the Amazon.ae variants on sale. No side effect: (to hide, alert lines)."""
    unmapped = [v for v in variants if not v["asin"]]
    mapped = [v for v in variants if v["asin"]]
    stale = [v for v in mapped if older(v, STALE_HOURS)]
    hard = [v for v in stale if HARD_STALE_HOURS > 0 and older(v, HARD_STALE_HOURS)]
    to_hide, alerts = [], []
    if len(unmapped) > MAX_UNMAPPED:
        alerts.append(f"{len(unmapped)} variants on sale have no ASIN (more than {MAX_UNMAPPED}): a data problem, they were "
                      "left as they are. Check the SKUs.")
    else:
        to_hide += unmapped
    if len(stale) > max(25, MAX_SHARE * len(mapped)):
        to_hide += hard
        alerts.append(f"{len(stale)} of {len(mapped)} variants on sale were not verified in the last {STALE_HOURS} h: the "
                      f"reading is probably broken. The {len(hard)} not verified for {HARD_STALE_HOURS:g} h were set to "
                      "Épuisé; the others stay on sale until the next check.")
    else:
        to_hide += stale
    if since_hours is not None:
        missed = [v for v in mapped if older(v, since_hours)]
        if len(missed) > max(25, MAX_SHARE * len(mapped)):
            alerts.append(f"this check did not read {len(missed)} of the {len(mapped)} variants on sale.")
    return to_hide, alerts


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "list"
    if not s.have_credentials():
        return
    now = dt.datetime.now(dt.timezone.utc)
    started = os.environ.get("RUN_STARTED_AT") or None
    since_hours = s.hours_since(started, now) if started else None
    if since_hours is not None and not 0 <= since_hours < 24:
        since_hours = None  # unreadable or absurd start time: fall back to the 6 h rule
    if mode in ("medx", "padelshop"):
        mod, name = (medx, "MedX") if mode == "medx" else (padelshop, "PadelShop.ae")
        variants = on_sale("medx" if mode == "medx" else "shop", now)
        bad = [v for v in variants if older(v, mod.STALE_HOURS)]
        print(f"{len(bad)} of {len(variants)} {name} variants on sale were not read in the last {mod.STALE_HOURS} h.")
        for b in bad[:60]:
            print("  not verified:", b["label"], "| last read:", b["seen"])
        if not bad or os.environ.get("DRY_RUN") == "1":
            return
        errors = hide(bad)
        print(f"{len(bad)} unverified variants set to Épuisé, {errors} Shopify errors.")
        sys.exit(f"ALERTE: {len(bad)} {name} variants had not been read for {mod.STALE_HOURS} h and were set to Épuisé.")
    variants = on_sale("amazon", now)
    if mode == "list":
        hours = since_hours if since_hours is not None else STALE_HOURS
        bad = [v for v in variants if v["asin"] and older(v, hours)]
        asins = sorted({b["asin"] for b in bad})
        print(f"{len(bad)} of {len(variants)} variants on sale were not read "
              + (f"by this check (started {started})" if since_hours is not None else f"in the last {STALE_HOURS} h")
              + f": {len(asins)} ASINs, {min(len(asins), MAX_RETRY)} read again now.")
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a") as f:
                f.write(f"count={len(asins[:MAX_RETRY])}\nasins={','.join(asins[:MAX_RETRY])}\n")
        return
    to_hide, alerts = decide(variants, since_hours)
    print(f"{len(variants)} variants on sale, {len(to_hide)} to set to Épuisé (no ASIN, or not verified in time).")
    for b in to_hide[:60]:
        print("  not verified:", b["label"], "| ASIN:", b["asin"], "| last read:", b["seen"])
    errors = 0
    if to_hide and os.environ.get("DRY_RUN") != "1":
        errors = hide(to_hide)
        print(f"{len(to_hide)} unverified variants set to Épuisé, {errors} Shopify errors.")
    if errors:
        alerts.append(f"{errors} Shopify errors while hiding unverified variants.")
    if alerts:
        sys.exit("ALERTE: " + " | ".join(alerts))


if __name__ == "__main__":
    main()
