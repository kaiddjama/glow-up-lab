#!/usr/bin/env python3
"""Merchandising order for every collection of a Shopify store: brands interleaved, best-sellers early,
product types and price bands varied. Only the display order changes; no product is edited or removed.

Usage: python3 -I reorder_collections.py [results_dir]
Settings come from environment variables (GitHub Actions secrets and variables): SHOPIFY_STORE and
SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET (or SHOPIFY_TOKEN). Optional:
  DRY_RUN=1    compute and report only, write nothing (default 0)
  FULL=1       rebuild every collection from scratch (default: keep the existing order, slot in only the
               products that are new to a collection or that came back in stock)
  ONLY=a,b     only these collection handles
  EXCLUDE=a,b  more handles to leave alone (added to the built-in list)

Each collection is switched to manual sort and ordered by ordering.py. Products the storefront hides (out of
stock, draft) go to the end so that what the customer sees is already well mixed. The ids of the products
placed in each collection are kept in an app-owned shop metafield, which is how a new product is recognised.
Collections ordered by price on purpose ("à petits prix") and technical ones are left alone.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ordering  # noqa: E402

API = "2025-07"
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
FULL = os.environ.get("FULL", "0") == "1"
ONLY = {h for h in os.environ.get("ONLY", "").split(",") if h}
EXCLUDE = {"frontpage", "eligible-welcome10"} | {h for h in os.environ.get("EXCLUDE", "").split(",") if h}
KEEP_SORTS = {"PRICE_ASC", "PRICE_DESC"}  # price-ordered by design
STATE_NS, STATE_KEY = "$app:merch", "placed"
POP_TAGS = ("best-seller", "incontournable")
NEW_SHARE_FULL = 0.4  # if more than this share of a collection is new, rebuild it instead of inserting

COLLECTIONS_Q = """query($after:String){ collections(first:100, after:$after){ pageInfo{hasNextPage endCursor}
  nodes{ id handle title sortOrder productsCount{count} } } }"""
PRODUCTS_Q = """query($after:String){ products(first:25, after:$after){ pageInfo{hasNextPage endCursor}
  nodes{ id title vendor productType status tags onlineStoreUrl totalInventory
    priceRangeV2{ minVariantPrice{ amount } }
    variants(first:25){ pageInfo{hasNextPage} nodes{ inventoryPolicy inventoryQuantity } } } } }"""
MEMBERS_Q = """query($id:ID!,$after:String){ collection(id:$id){ products(first:250, after:$after){
  pageInfo{hasNextPage endCursor} nodes{ id } } } }"""
SORT_M = """mutation($i:CollectionInput!){ collectionUpdate(input:$i){ userErrors{field message} } }"""
REORDER_M = """mutation($id:ID!,$m:[MoveInput!]!){ collectionReorderProducts(id:$id, moves:$m){
  job{id done} userErrors{field message} } }"""
JOB_Q = """query($id:ID!){ job(id:$id){ done } }"""
STATE_Q = """query{ shop{ id metafield(namespace:"$app:merch", key:"placed"){ value } } }"""
STATE_M = """mutation($m:[MetafieldsSetInput!]!){ metafieldsSet(metafields:$m){ userErrors{field message} } }"""


def token():
    if not os.environ.get("SHOPIFY_TOKEN"):
        req = urllib.request.Request(
            f"https://{os.environ['SHOPIFY_STORE']}/admin/oauth/access_token",
            data=urllib.parse.urlencode({"grant_type": "client_credentials",
                                         "client_id": os.environ["SHOPIFY_CLIENT_ID"],
                                         "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"]}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=30) as r:
            os.environ["SHOPIFY_TOKEN"] = json.load(r)["access_token"]
    return os.environ["SHOPIFY_TOKEN"]


def gql(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    for attempt in range(8):
        req = urllib.request.Request(
            f"https://{os.environ['SHOPIFY_STORE']}/admin/api/{API}/graphql.json", data=body,
            headers={"Content-Type": "application/json", "X-Shopify-Access-Token": token()})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504):
                time.sleep(2 + attempt * 3)
                continue
            raise
        errors = res.get("errors")
        if errors and any("THROTTLED" in json.dumps(e) for e in errors):
            time.sleep(3 + attempt * 3)
            continue
        if errors:
            raise RuntimeError(errors)
        return res["data"]
    raise RuntimeError("Shopify kept throttling")


def paged(query, variables, path):
    after = None
    while True:
        data = gql(query, dict(variables, after=after))
        for key in path:
            data = data[key]
        yield from data["nodes"]
        if not data["pageInfo"]["hasNextPage"]:
            return
        after = data["pageInfo"]["endCursor"]


BRAND_SUFFIXES = (" professional makeup", " professional", " cosmetics", " cosmétiques", " paris", " new york",
                  " beauty", " skincare", " baby")  # "NYX" and "NYX Professional Makeup" are one brand


def brand_key(vendor):
    b = (vendor or "").strip().lower()
    for suffix in BRAND_SUFFIXES:
        if b.endswith(suffix) and len(b) > len(suffix) + 1:
            b = b[:-len(suffix)].strip()
    return b


def num(gid):
    return gid.rsplit("/", 1)[-1]


def load_products():
    products = {}
    for p in paged(PRODUCTS_Q, {}, ("products",)):
        variants = p["variants"]["nodes"]
        if variants and not p["variants"]["pageInfo"]["hasNextPage"]:
            in_stock = any(v["inventoryPolicy"] == "CONTINUE" or (v["inventoryQuantity"] or 0) > 0
                           for v in variants)
        else:
            in_stock = (p["totalInventory"] or 0) > 0
        tags = p["tags"] or []
        rayon = next((t[6:] for t in tags if t.startswith("rayon:")), None) or \
            next((t[4:] for t in tags if t.startswith("sub:")), None) or (p["productType"] or "").lower()
        brand = brand_key(p["vendor"]) or "?" + num(p["id"])
        title = (p["title"] or "").lower()
        if title.startswith((p["vendor"] or "?").strip().lower()):
            title = title[len((p["vendor"] or "").strip()):]
        elif title.startswith(brand):
            title = title[len(brand):]
        words = re.findall(r"[a-zà-ÿ0-9]+", title)
        products[p["id"]] = {
            "id": p["id"], "brand": brand, "type": rayon, "line": " ".join(words[:2]) if len(words) >= 2 else "",
            "pop": sum(t in tags for t in POP_TAGS), "key": num(p["id"]), "band": 0,
            "price": float(p["priceRangeV2"]["minVariantPrice"]["amount"]),
            "active": p["status"] == "ACTIVE", "in_stock": in_stock, "published": bool(p["onlineStoreUrl"])}
    # onlineStoreUrl is null when the app cannot see the sales channel: then do not trust it
    if products and sum(not p["published"] for p in products.values() if p["active"]) > \
            0.5 * sum(p["active"] for p in products.values()):
        for p in products.values():
            p["published"] = True
    for p in products.values():
        p["visible"] = p["active"] and p["in_stock"] and p["published"]
    return products


def load_state():
    shop = gql(STATE_Q)["shop"]
    raw = (shop.get("metafield") or {}).get("value")
    try:
        return shop["id"], json.loads(raw) if raw else {}
    except ValueError:
        return shop["id"], {}


def save_state(shop_id, state):
    res = gql(STATE_M, {"m": [{"ownerId": shop_id, "namespace": STATE_NS, "key": STATE_KEY, "type": "json",
                               "value": json.dumps(state, separators=(",", ":"))}]})
    errs = res["metafieldsSet"]["userErrors"]
    if errs:
        print("WARNING: could not save the placed-products state:", errs)


def set_bands(items):
    prices = sorted(p["price"] for p in items)
    for p in items:
        rank = sum(x < p["price"] for x in prices)
        p["band"] = min(3, rank * 4 // max(len(prices), 1))


def wait_job(job):
    if not job or job.get("done"):
        return
    for _ in range(120):
        time.sleep(1)
        if gql(JOB_Q, {"id": job["id"]})["job"]["done"]:
            return
    print("WARNING: reorder job still running after 2 minutes")


def apply_order(col, current, desired):
    if col["sortOrder"] != "MANUAL":
        errs = gql(SORT_M, {"i": {"id": col["id"], "sortOrder": "MANUAL"}})["collectionUpdate"]["userErrors"]
        if errs:
            raise RuntimeError(errs)
        first = 0
    else:
        first = next((i for i, (a, b) in enumerate(zip(current, desired)) if a != b), None)
        if first is None:
            return 0
    moved = 0
    for start in range(first, len(desired), 250):
        moves = [{"id": gid, "newPosition": str(i)} for i, gid in enumerate(desired[start:start + 250], start)]
        res = gql(REORDER_M, {"id": col["id"], "m": moves})["collectionReorderProducts"]
        if res["userErrors"]:
            raise RuntimeError(res["userErrors"])
        wait_job(res["job"])
        moved += len(moves)
    return moved


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "results"
    os.makedirs(out_dir, exist_ok=True)
    if not (os.environ.get("SHOPIFY_STORE") and (os.environ.get("SHOPIFY_TOKEN") or os.environ.get("SHOPIFY_CLIENT_ID"))):
        print("No Shopify credentials: nothing to do.")
        return
    products = load_products()
    shop_id, state = load_state()
    print(f"{len(products)} products, {sum(p['visible'] for p in products.values())} visible, "
          f"{'DRY RUN, ' if DRY_RUN else ''}{'full rebuild' if FULL else 'incremental'}")
    report, new_state = [], dict(state)
    for col in paged(COLLECTIONS_Q, {}, ("collections",)):
        handle = col["handle"]
        if ONLY and handle not in ONLY:
            continue
        if handle in EXCLUDE or "archive" in col["title"].lower() or col["sortOrder"] in KEEP_SORTS \
                or col["productsCount"]["count"] < 3:
            continue
        current = [n["id"] for n in paged(MEMBERS_Q, {"id": col["id"]}, ("collection", "products"))]
        members = [products[g] for g in current if g in products]
        visible = [p for p in members if p["visible"]]
        hidden = [p["id"] for p in members if not p["visible"]]
        hidden += [g for g in current if g not in products]
        if len(visible) < 3:
            continue
        set_bands(visible)
        known = set(state.get(num(col["id"]), []))
        fresh = [p for p in visible if p["key"] not in known]
        before = ordering.metrics([p for g in current for p in [products.get(g)] if p and p["visible"]])
        if FULL or num(col["id"]) not in state or len(fresh) > NEW_SHARE_FULL * len(visible):
            mode, order = "rebuilt", ordering.build(visible)
        else:
            placed = [p for g in current for p in [products.get(g)] if p and p["visible"] and p["key"] in known]
            mode = f"{len(fresh)} inserted" if fresh else "unchanged"
            order = ordering.insert(placed, fresh) if fresh else placed
            if col["sortOrder"] != "MANUAL":
                mode = "switched to manual"
        desired = [p["id"] for p in order] + hidden
        assert sorted(desired) == sorted(current), "order must contain the same products"
        moved = 0
        if desired != current or col["sortOrder"] != "MANUAL":
            if not DRY_RUN:
                moved = apply_order(col, current, desired)
        new_state[num(col["id"])] = [p["key"] for p in order]
        after = ordering.metrics(order)
        report.append({"handle": handle, "title": col["title"], "mode": mode, "moved": moved,
                       "hidden": len(hidden), "before": before, "after": after})
        print(f"{handle:42} {mode:18} n={after['n']:4} adjacent {before['adjacent_same_brand']:3}->"
              f"{after['adjacent_same_brand']:<3} within4 {before['same_brand_within_4']:3}->"
              f"{after['same_brand_within_4']:<3} run {before['longest_brand_run']:2}->"
              f"{after['longest_brand_run']:<2} brands/page1 {before['brands_on_first_page']:2}->"
              f"{after['brands_on_first_page']}")
    if not DRY_RUN:
        save_state(shop_id, new_state)
    with open(os.path.join(out_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=1)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(f"### Collection order ({'dry run' if DRY_RUN else 'applied'})\n\n"
                    "| collection | action | products | adjacent same brand | longest brand run | brands on page 1 |\n"
                    "|---|---|---|---|---|---|\n")
            for r in report:
                f.write(f"| {r['handle']} | {r['mode']} | {r['after']['n']} | {r['before']['adjacent_same_brand']} → "
                        f"{r['after']['adjacent_same_brand']} | {r['before']['longest_brand_run']} → "
                        f"{r['after']['longest_brand_run']} | {r['before']['brands_on_first_page']} → "
                        f"{r['after']['brands_on_first_page']} |\n")


if __name__ == "__main__":
    main()
