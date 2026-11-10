#!/usr/bin/env python3
"""MedX Pharmacy price and stock sync for the Shopify store (second supplier next to Amazon.ae, see medx.py).

Usage: python3 -I medx_sync.py results_dir
Same settings as amazon_sync.py (SHOPIFY_STORE, SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET, PRICE_FORMULA). DRY_RUN=1 reads
and reports only. Needs no browser: the MedX pages are plain HTML.

For every variant whose SKU is "MEDX-<alias>" (active products, plus hidden ones tagged epuise-auto or medx-revue) it reads
the MedX page and sets: Épuisé (inventoryPolicy DENY) unless the stock is high enough (see medx.sellable), the price from
the same formula as the Amazon.ae products, and the supplier.* metafields that coverage.py and park_soldout.py rely on.
Products are only hidden / shown again by park_soldout.py (tag epuise-auto); products tagged medx-revue are waiting for
Hoodo's go and are never put online here.
"""
import datetime as dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I does not add the script folder
import amazon_sync as s  # noqa: E402
import medx  # noqa: E402

REVIEW_TAG = "medx-revue"  # draft waiting for Hoodo's approval: kept up to date, never published by a script
STOCK_GUARD = float(os.environ.get("STOCK_GUARD", "0.35"))  # share of variants that may go Épuisé at once before an alert
MAX_ERRORS = 0.5  # more unreadable pages than this share = reading is broken: nothing changed, alert
DELAY = float(os.environ.get("DELAY", "0.7"))

Q = """query($after:String,$q:String!){ products(first:50, after:$after, query:$q){
  pageInfo{hasNextPage endCursor}
  nodes{ id handle tags
    weight: metafield(namespace:"internal", key:"weight_g"){value}
    variants(first:100){ nodes{ id title sku price inventoryPolicy
      inventoryItem{ measurement{ weight{ value unit } } } } } } } }"""


def load_rows():
    rows, seen = [], set()
    for search, parked in (("status:active", False), (f"status:draft tag:{REVIEW_TAG}", True),
                           (f"status:draft tag:{s.OUT_TAG}", True)):
        after = None
        while True:
            data = s.gql(Q, {"after": after, "q": search})["products"]
            for p in data["nodes"]:
                if p["id"] in seen:
                    continue
                mine = [v for v in p["variants"]["nodes"] if medx.slug_of(v.get("sku"))]
                if not mine:
                    continue
                mixed = len(mine) < len(p["variants"]["nodes"])  # variants of another supplier on the same product
                seen.add(p["id"])
                grams = float(p["weight"]["value"]) if p.get("weight") else None
                for v in mine:  # the weight of the variant itself first (formats differ), then the product's, then the default
                    w = ((v.get("inventoryItem") or {}).get("measurement") or {}).get("weight") or {}
                    factor = {"GRAMS": 1, "KILOGRAMS": 1000, "POUNDS": 453.6, "OUNCES": 28.35}.get(w.get("unit"))
                    vg = float(w["value"]) * factor if factor and w.get("value") else grams
                    rows.append({"productId": p["id"], "handle": p["handle"], "variantId": v["id"], "variant": v["title"],
                                 "slug": medx.slug_of(v["sku"]), "price": float(v["price"]), "policy": v["inventoryPolicy"],
                                 "grams": vg or s.DEFAULT_WEIGHT_G, "parked": parked, "mixed": mixed,
                                 "review": REVIEW_TAG in (p.get("tags") or [])})
            if not data["pageInfo"]["hasNextPage"]:
                break
            after = data["pageInfo"]["endCursor"]
    return rows


def main():
    if not (os.environ.get("SHOPIFY_STORE") and (os.environ.get("SHOPIFY_TOKEN") or os.environ.get("SHOPIFY_CLIENT_SECRET"))):
        print("No Shopify credentials set: nothing to do.")
        return
    if not s.AED_TO_FDJ:
        sys.exit("ALERTE: PRICE_FORMULA is not set: no price can be computed, nothing changed.")
    dry = os.environ.get("DRY_RUN") == "1"
    outdir = sys.argv[1] if len(sys.argv) > 1 else "results"
    os.makedirs(outdir, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = load_rows()
    slugs = sorted({r["slug"] for r in rows})
    print(f"{len(rows)} MedX variants in {len({r['productId'] for r in rows})} products, {len(slugs)} pages to read.")
    pages = {}
    for n, slug in enumerate(slugs, 1):
        pages[slug] = medx.fetch(slug)
        time.sleep(DELAY)
    failed = [x for x in slugs if pages[x].get("error")]
    report = {"at": now, "variants": len(rows), "errors": [], "changes": [], "skipped": []}
    for slug in failed:
        report["errors"].append({"slug": slug, "error": pages[slug]["error"]})
    if rows and len(failed) > MAX_ERRORS * len(slugs):
        sys.exit(f"ALERTE: {len(failed)} of {len(slugs)} MedX pages could not be read (blocked or layout changed): "
                 "nothing changed here; coverage.py sets what stays unread to Épuisé.")

    live = [r for r in rows if not pages[r["slug"]].get("error")]
    decisions = []
    for r in live:
        pg = pages[r["slug"]]
        on = r["policy"] == "CONTINUE"
        sell = medx.sellable(pg, on)
        decisions.append((r, pg, on, sell))
    newly_out = sum(1 for r, pg, on, sell in decisions if on and not sell and not pg.get("gone"))
    stock_guard = len(live) >= 10 and newly_out > STOCK_GUARD * len(live)
    if stock_guard:  # hiding is the safe direction, so it is applied anyway; the owner is warned at the end
        print(f"Stock guard: {newly_out} of {len(live)} variants go Épuisé at once (probably a misread, they come back by themselves).")

    outs, others, fields = {}, {}, []
    for r, pg, on, sell in decisions:
        fields.append({"ownerId": r["variantId"], "namespace": "supplier", "key": "variant_checked_at",
                       "type": "date_time", "value": now})
        upd = {"id": r["variantId"]}
        new_policy = "CONTINUE" if sell else "DENY"
        if new_policy != r["policy"]:
            upd["inventoryPolicy"] = new_policy
        if sell and not pg.get("gone"):
            new = s.formula(pg["aed"], r["grams"])
            if r["parked"] or abs(new - r["price"]) >= 50:
                if r["price"] and abs(new - r["price"]) / r["price"] > s.MAX_CHANGE and not r["review"]:
                    report["skipped"].append({"handle": r["handle"], "variant": r["variant"], "aed": pg["aed"],
                                              "now": r["price"], "formula": new})
                else:
                    upd["price"] = str(new)
            fields.append({"ownerId": r["variantId"], "namespace": "internal", "key": "cost_aed",
                           "type": "number_decimal", "value": f"{pg['aed']:.2f}"})
            fields.append({"ownerId": r["variantId"], "namespace": "supplier", "key": "delivery_eta",
                           "type": "single_line_text_field", "value": medx.eta()})
            fields.append({"ownerId": r["variantId"], "namespace": "supplier", "key": "delivery_range",
                           "type": "single_line_text_field", "value": "standard"})
        if len(upd) > 1:
            report["changes"].append({"handle": r["handle"], "variant": r["variant"], "slug": r["slug"], "aed": pg.get("aed"),
                                      "qty": pg.get("qty"), "oldPrice": r["price"], **{k: v for k, v in upd.items() if k != "id"}})
            (outs if upd.get("inventoryPolicy") == "DENY" else others).setdefault(r["productId"], []).append(upd)
    mixed_ids = {r["productId"] for r in rows if r["mixed"]}  # product-level supplier fields are left to the other supplier's sync
    for pid in {r["productId"] for r, *_ in decisions} - mixed_ids:
        mine = [(pg, sell) for r, pg, on, sell in decisions if r["productId"] == pid]
        fields.append({"ownerId": pid, "namespace": "supplier", "key": "in_stock", "type": "boolean",
                       "value": "true" if any(sell for _, sell in mine) else "false"})
        fields.append({"ownerId": pid, "namespace": "supplier", "key": "checked_at", "type": "date_time", "value": now})
        fields.append({"ownerId": pid, "namespace": "supplier", "key": "delivery_days", "type": "number_integer",
                       "value": str(medx.DUBAI_DAYS)})

    errors = 0
    if not dry:
        for group in (outs, others):  # hide first, then prices and put back on sale
            for pid, ups in group.items():
                res = s.gql(s.PRICES_M, {"p": pid, "v": ups})["productVariantsBulkUpdate"]["userErrors"]
                errors += len(res)
                for e in res:
                    print("price/stock error:", pid, e)
        for i in range(0, len(fields), 25):
            res = s.gql(s.META_M, {"m": fields[i:i + 25]})["metafieldsSet"]["userErrors"]
            errors += len(res)
            for e in res:
                print("metafield error:", e)
    path = os.path.join(outdir, f"medx-{now[:13].replace(':', '')}.json")
    json.dump(report, open(path, "w"), indent=1, ensure_ascii=False)
    went_out = sum(c.get("inventoryPolicy") == "DENY" for c in report["changes"])
    back = sum(c.get("inventoryPolicy") == "CONTINUE" for c in report["changes"])
    prices = sum("price" in c for c in report["changes"])
    low = sorted((pg["qty"], r["handle"]) for r, pg, on, sell in decisions if on and sell and pg["qty"] < 2 * medx.MIN_QTY)[:8]
    print(f"{'DRY RUN: ' if dry else ''}{len(live)} variants read, {len(failed)} pages not read, {prices} prices changed, "
          f"{went_out} set to Épuisé, {back} back on sale, {len(report['skipped'])} big price changes held, {errors} Shopify errors. "
          f"Lowest stocks still on sale: {low}. Report: {path}")
    if stock_guard and not dry:
        sys.exit(f"ALERTE: {newly_out} MedX variants went Épuisé at once (probably a misread, or a real shortage): check the MedX pages.")
    if errors and not dry:
        sys.exit(f"ALERTE: {errors} Shopify errors.")


if __name__ == "__main__":
    main()
