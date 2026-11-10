#!/usr/bin/env python3
"""Creates (or lists, or publishes) the MedX Pharmacy products described in medx/selection.json.

  python3 -I medx_create.py create    creates every product not already in the shop, as a DRAFT tagged medx-revue
                                      (waiting for Hoodo's go; medx_sync.py keeps its price and stock up to date).
                                      Every variant is read on MedX first: a page that cannot be read, a product that is
                                      not published or a stock below MIN_CREATE_QTY (20) is left out, and said so.
  python3 -I medx_create.py publish   puts online (ACTIVE + Online Store channel) the medx-revue products that have at
                                      least one variant on sale, and removes the review tag. Only run after Hoodo's go.
DRY_RUN=1 reports only. Photos are the JPEG files of medx/photos/, served by raw.githubusercontent.com at the commit
being run (GITHUB_SHA); the photo folder is removed from the repository once the products exist.
Same Shopify settings as amazon_sync.py; PRICE_FORMULA is needed for the prices.
"""
import json
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I does not add the script folder
import amazon_sync as s  # noqa: E402
import medx  # noqa: E402
import medx_sync  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_CREATE_QTY = int(os.environ.get("MEDX_MIN_CREATE_QTY", "20"))  # stock needed to create a variant
PRODUCT_TYPE = "Compléments & nutrition"
PUBLICATION = os.environ.get("ONLINE_STORE_PUBLICATION", "gid://shopify/Publication/338148819125")  # Online Store channel
REPO = os.environ.get("GITHUB_REPOSITORY", "kaiddjama/glow-up-lab")
REF = os.environ.get("GITHUB_SHA", "main")

FIND_Q = """query($q:String!){ products(first:5, query:$q){ nodes{ id handle } } }"""
SET_M = """mutation($input:ProductSetInput!){ productSet(synchronous:true, input:$input){
  product{ id handle media(first:50){ nodes{ id alt status } } variants(first:100){ nodes{ id sku } } }
  userErrors{ field message code } } }"""
MEDIA_Q = """query($id:ID!){ product(id:$id){ media(first:50){ nodes{ id alt status } } } }"""
APPEND_M = """mutation($p:ID!,$m:[ProductVariantAppendMediaInput!]!){ productVariantAppendMedia(productId:$p, variantMedia:$m){
  userErrors{ field message } } }"""
PUBLISH_M = """mutation($id:ID!,$p:ID!){publishablePublish(id:$id, input:[{publicationId:$p}]){userErrors{field message}}}"""


def html(p):
    items = "".join(f"<li>{x}</li>" for x in p["points"])
    return f"<p>{p['intro']}</p><ul>{items}</ul><p>{p['note']}</p>"


def photo_url(name):
    return f"https://raw.githubusercontent.com/{REPO}/{REF}/stock-sync/medx/photos/{urllib.parse.quote(name)}"


def create(dry):
    selection = json.load(open(os.path.join(HERE, "medx", "selection.json"), encoding="utf-8"))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    made, skipped, errors = 0, [], 0
    for p in selection:
        if s.gql(FIND_Q, {"q": f"handle:{p['handle']}"})["products"]["nodes"]:
            print("already exists:", p["handle"])
            continue
        ok = []
        for v in p["variants"]:
            pg = medx.fetch(v["slug"])
            time.sleep(0.7)
            if pg.get("error") or pg.get("gone"):
                skipped.append((p["handle"], v["label"], pg.get("error") or "page removed"))
            elif not pg["publish"] or pg["qty"] < MIN_CREATE_QTY:
                skipped.append((p["handle"], v["label"], f"stock {pg['qty']} or not published"))
            else:
                ok.append((v, pg))
        if not ok:
            print("nothing available, not created:", p["handle"])
            continue
        grams = p["weight_g"]
        variants, files = [], []
        for v, pg in ok:
            price = s.formula(pg["aed"], grams)
            alt = f"{p['title']} - {v['label']}"
            files.append({"originalSource": photo_url(v["photo"]), "alt": alt, "contentType": "IMAGE"})
            variants.append({
                "optionValues": [{"optionName": p["option"], "name": v["label"]}], "sku": f"MEDX-{v['slug']}", "price": str(price),
                "inventoryPolicy": "DENY",  # medx_sync.py puts it on sale after reading the stock again
                "inventoryItem": {"tracked": True, "measurement": {"weight": {"value": grams / 1000, "unit": "KILOGRAMS"}}},
                "metafields": [
                    {"namespace": "internal", "key": "cost_aed", "type": "number_decimal", "value": f"{pg['aed']:.2f}"},
                    {"namespace": "supplier", "key": "variant_checked_at", "type": "date_time", "value": now},
                    {"namespace": "supplier", "key": "delivery_eta", "type": "single_line_text_field", "value": medx.eta()},
                    {"namespace": "supplier", "key": "delivery_range", "type": "single_line_text_field", "value": "standard"}]})
        tags = list(p["tags"]) + [medx_sync.REVIEW_TAG]
        if min(float(v["price"]) for v in variants) <= 3300 and "petit-prix-sport" not in tags:
            tags.append("petit-prix-sport")
        inp = {
            "title": p["title"], "handle": p["handle"], "vendor": p["vendor"], "productType": PRODUCT_TYPE, "status": "DRAFT",
            "tags": tags, "descriptionHtml": html(p),
            "seo": {"title": p["seo_title"], "description": p["seo_desc"]},
            "productOptions": [{"name": p["option"], "values": [{"name": v["label"]} for v, _ in ok]}],
            "variants": variants, "files": files,
            "metafields": [
                {"namespace": "internal", "key": "supplier", "type": "single_line_text_field", "value": "MedX Pharmacy (Dubaï)"},
                {"namespace": "internal", "key": "supplier_ref", "type": "single_line_text_field", "value": f"MEDX {ok[0][0]['slug']}"},
                {"namespace": "internal", "key": "weight_g", "type": "number_integer", "value": str(grams)},
                {"namespace": "supplier", "key": "checked_at", "type": "date_time", "value": now},
                {"namespace": "supplier", "key": "in_stock", "type": "boolean", "value": "true"},
                {"namespace": "supplier", "key": "delivery_days", "type": "number_integer", "value": str(medx.DUBAI_DAYS)}]}
        print(("DRY RUN: would create " if dry else "creating ") + f"{p['handle']} ({len(ok)} variants, "
              f"{min(float(v['price']) for v in variants):.0f}-{max(float(v['price']) for v in variants):.0f} Fdj)")
        if dry:
            continue
        res = s.gql(SET_M, {"input": inp})["productSet"]
        if res["userErrors"]:
            errors += 1
            print("error:", p["handle"], res["userErrors"])
            continue
        made += 1
        prod = res["product"]
        # photos: wait until Shopify has processed them, then link each to its variant
        by_alt = {}
        for _ in range(60):
            nodes = s.gql(MEDIA_Q, {"id": prod["id"]})["product"]["media"]["nodes"]
            by_alt = {m["alt"]: m for m in nodes}
            if len(nodes) >= len(files) and all(m["status"] in ("READY", "FAILED") for m in nodes):
                break
            time.sleep(5)
        links = []
        sku_to_id = {v["sku"]: v["id"] for v in prod["variants"]["nodes"]}
        for v, _ in ok:
            m = by_alt.get(f"{p['title']} - {v['label']}")
            if not m or m["status"] != "READY":
                errors += 1
                print("photo not ready:", p["handle"], v["label"], m and m["status"])
                continue
            links.append({"variantId": sku_to_id[f"MEDX-{v['slug']}"], "mediaIds": [m["id"]]})
        if links:
            errs = s.gql(APPEND_M, {"p": prod["id"], "m": links})["productVariantAppendMedia"]["userErrors"]
            if errs:
                errors += 1
                print("photo link error:", p["handle"], errs)
    print(f"{made} products created, {len(skipped)} variants left out, {errors} errors.")
    for x in skipped:
        print("  left out:", x)
    if errors and not dry:
        sys.exit(f"ALERTE: {errors} errors while creating MedX products.")


def publish(dry):
    after, products = None, []
    while True:
        data = s.gql(medx_sync.Q, {"after": after, "q": f"status:draft tag:{medx_sync.REVIEW_TAG}"})["products"]
        products += [p for p in data["nodes"] if any(medx.slug_of(v.get("sku")) for v in p["variants"]["nodes"])]
        if not data["pageInfo"]["hasNextPage"]:
            break
        after = data["pageInfo"]["endCursor"]
    done = 0
    for p in products:
        on_sale = [v for v in p["variants"]["nodes"] if v["inventoryPolicy"] == "CONTINUE"]
        if not on_sale:
            print("no variant on sale yet, left as a draft:", p["handle"])
            continue
        print(("DRY RUN: would publish " if dry else "publishing ") + p["handle"])
        if dry:
            continue
        for q, vars_ in ((s.STATUS_M, {"p": {"id": p["id"], "status": "ACTIVE"}}),
                         (s.TAGS_REMOVE_M, {"id": p["id"], "t": [medx_sync.REVIEW_TAG]}),
                         (PUBLISH_M, {"id": p["id"], "p": PUBLICATION})):
            errs = next(iter(s.gql(q, vars_).values()))["userErrors"]
            if errs:
                print("error:", p["handle"], errs)
        done += 1
    print(f"{done} products put online.")


def main():
    if not (os.environ.get("SHOPIFY_STORE") and (os.environ.get("SHOPIFY_TOKEN") or os.environ.get("SHOPIFY_CLIENT_SECRET"))):
        print("No Shopify credentials set: nothing to do.")
        return
    if not s.AED_TO_FDJ:
        sys.exit("ALERTE: PRICE_FORMULA is not set.")
    mode = sys.argv[1] if len(sys.argv) > 1 else "create"
    dry = os.environ.get("DRY_RUN") == "1"
    {"create": create, "publish": publish}[mode](dry)


if __name__ == "__main__":
    main()
