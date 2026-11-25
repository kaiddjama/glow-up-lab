#!/usr/bin/env python3
"""Creates (or extends) the Amazon.ae makeup products described in amz/selection.json, as hidden DRAFTS tagged epuise-auto.

  python3 -I amz_create.py        for every entry: creates the product when the handle is not in the shop yet, or adds the
                                  variants whose SKU (the ASIN) the product does not have yet when the entry says "extend".
DRY_RUN=1 reports only. Nothing goes online here: the targeted check (amazon_sync.py with ONLY_ASINS) reads each ASIN again,
sets the price and puts the product on sale only when stock and delay are right (<= 2 days to Dubai); a second step
publishes the products to the Online Store channel.
Photos: the main Amazon photo of each shade (selection "img") is downloaded here, put on a 1600 px pure-white square canvas
and uploaded to Shopify (staged upload), so nothing is stored in the repository. Same Shopify settings as amazon_sync.py.
Non-makeup products: an entry may carry "product_type" and "tags_base" (the full tag list without epuise-auto).
"""
import io
import json
import os
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I does not add the script folder
import amazon_sync as s  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PRODUCT_TYPE = "Maquillage"

FIND_Q = """query($q:String!){ products(first:5, query:$q){ nodes{ id handle title status variants(first:100){ nodes{ id sku } } } } }"""
VARIANTS_M = """mutation($p:ID!,$v:[ProductVariantsBulkInput!]!){ productVariantsBulkCreate(productId:$p, variants:$v){
  productVariants{ id sku } userErrors{ field message code } } }"""
UPDATE_M = """mutation($i:ProductUpdateInput!,$m:[CreateMediaInput!]){ productUpdate(product:$i, media:$m){
  product{ id handle } userErrors{ field message } } }"""
SET_M = """mutation($input:ProductSetInput!){ productSet(synchronous:true, input:$input){
  product{ id handle variants(first:100){ nodes{ id sku } } } userErrors{ field message code } } }"""
MEDIA_Q = """query($id:ID!){ product(id:$id){ media(first:100){ nodes{ id alt status } } } }"""
APPEND_M = """mutation($p:ID!,$m:[ProductVariantAppendMediaInput!]!){ productVariantAppendMedia(productId:$p, variantMedia:$m){
  userErrors{ field message } } }"""
STAGED_M = """mutation($i:[StagedUploadInput!]!){ stagedUploadsCreate(input:$i){
  stagedTargets{ url resourceUrl parameters{ name value } } userErrors{ field message } } }"""


def html(p):
    items = "".join(f"<li>{x}</li>" for x in p["points"])
    return f"<p>{p['intro']}</p><ul>{items}</ul>"


def white_square(raw):
    """Main photo -> 1600 px square, pure white (#FFFFFF) background, product centred with a margin."""
    from PIL import Image  # installed by the workflow
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    im.thumbnail((1480, 1480), Image.LANCZOS)
    px = im.load()
    for y in range(im.height):  # near-white pixels (Amazon backgrounds are 250-255) become exactly 255
        for x in range(im.width):
            r, g, b = px[x, y]
            if r >= 247 and g >= 247 and b >= 247:
                px[x, y] = (255, 255, 255)
    canvas = Image.new("RGB", (1600, 1600), (255, 255, 255))
    canvas.paste(im, ((1600 - im.width) // 2, (1600 - im.height) // 2))
    out = io.BytesIO()
    canvas.save(out, "JPEG", quality=92)
    return out.getvalue()


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read()
        except OSError:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("photo download failed: " + url)


def upload(data, name):
    """Staged upload of one JPEG to Shopify; returns the resourceUrl to use as originalSource."""
    t = s.gql(STAGED_M, {"i": [{"resource": "IMAGE", "filename": name, "mimeType": "image/jpeg", "httpMethod": "POST",
                                "fileSize": str(len(data))}]})["stagedUploadsCreate"]
    if t["userErrors"] or not t["stagedTargets"]:
        raise RuntimeError(f"staged upload: {t['userErrors']}")
    tg = t["stagedTargets"][0]
    boundary = uuid.uuid4().hex
    body = b""
    for prm in tg["parameters"]:
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{prm["name"]}"\r\n\r\n{prm["value"]}\r\n'.encode()
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
             f"Content-Type: image/jpeg\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(tg["url"], data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        r.read()
    return tg["resourceUrl"]


def photo_file(p, v):
    raw = download(v["img"])
    return {"originalSource": upload(white_square(raw), f"{v['asin']}.jpg"), "alt": f"{p['title']} - {v['label']}",
            "contentType": "IMAGE"}


def variant_input(p, v, now, bulk=False):
    grams = v.get("weight_g", p["weight_g"])
    price = s.formula(v["aed"], grams)
    out = {
        "optionValues": [{"optionName": p.get("option", "Teinte"), "name": v["label"]}], "sku": v["asin"], "price": str(price),
        "inventoryPolicy": "CONTINUE",  # the targeted check puts it to DENY (Épuisé) when stock / delay are not right
        "inventoryItem": {"tracked": True, "measurement": {"weight": {"value": grams / 1000, "unit": "KILOGRAMS"}}},
        "metafields": [{"namespace": "internal", "key": "cost_aed", "type": "number_decimal", "value": f"{v['aed']:.2f}"}]}
    if bulk:
        out["inventoryItem"]["sku"] = out.pop("sku")
    return out


def wait_media(pid, alts):
    by_alt = {}
    for _ in range(80):
        nodes = s.gql(MEDIA_Q, {"id": pid})["product"]["media"]["nodes"]
        by_alt = {m["alt"]: m for m in nodes}
        if all(a in by_alt and by_alt[a]["status"] in ("READY", "FAILED") for a in alts):
            break
        time.sleep(5)
    return by_alt


def link_photos(p, pid, vs, sku_to_id, by_alt):
    errors, links = 0, []
    for v in vs:
        m = by_alt.get(f"{p['title']} - {v['label']}")
        if not m or m["status"] != "READY":
            errors += 1
            print("photo not ready:", p["handle"], v["label"], m and m["status"])
            continue
        links.append({"variantId": sku_to_id[v["asin"]], "mediaIds": [m["id"]]})
    if links:
        errs = s.gql(APPEND_M, {"p": pid, "m": links})["productVariantAppendMedia"]["userErrors"]
        if errs:
            errors += 1
            print("photo link error:", p["handle"], errs)
    return errors


def tags_of(p):
    base = p.get("tags_base") or ["cat:maquillage", "concern:maquillage", "maquillage", "nouveau", p["rayon"], p["sub"],
                                  "stock:sur-commande", "sur-commande"]
    base = base + [s.OUT_TAG]
    return base + [t for t in p.get("tags", []) if t not in base]


NOPHOTO_Q = """query($id:ID!){ product(id:$id){ variants(first:100){ nodes{ id sku media(first:1){ nodes{ id } } } } } }"""


def fix_photos(p, prod):
    """Variants of the selection that exist but have no photo yet (an interrupted run): uploads and links the photos."""
    want = {v["asin"]: v for v in p["variants"]}
    nodes = s.gql(NOPHOTO_Q, {"id": prod["id"]})["product"]["variants"]["nodes"]
    todo = [(n, want[n["sku"]]) for n in nodes if n["sku"] in want and not n["media"]["nodes"]]
    if not todo:
        return 0
    print(f"adding the missing photos of {prod['handle']}: {len(todo)}")
    files = [photo_file(p, v) for _, v in todo]
    media = [{"originalSource": f["originalSource"], "alt": f["alt"], "mediaContentType": "IMAGE"} for f in files]
    errs = s.gql(UPDATE_M, {"i": {"id": prod["id"]}, "m": media})["productUpdate"]["userErrors"]
    if errs:
        print("update error:", p["handle"], errs)
        return 1
    by_alt = wait_media(prod["id"], [f["alt"] for f in files])
    return link_photos(p, prod["id"], [v for _, v in todo], {n["sku"]: n["id"] for n, _ in todo}, by_alt)


def extend(p, prod, now, dry):
    have = {v["sku"] for v in prod["variants"]["nodes"]}
    new = [v for v in p["variants"] if v["asin"] not in have]
    print(("DRY RUN: would extend " if dry else "extending ") + f"{prod['handle']} with {len(new)} variants: "
          + ", ".join(v["label"] for v in new))
    if dry:
        return 0
    if not new:
        return fix_photos(p, prod)
    errors = 0
    files = [photo_file(p, v) for v in new]
    media = [{"originalSource": f["originalSource"], "alt": f["alt"], "mediaContentType": "IMAGE"} for f in files]
    res = s.gql(VARIANTS_M, {"p": prod["id"], "v": [variant_input(p, v, now, bulk=True) for v in new]})["productVariantsBulkCreate"]
    if res["userErrors"]:
        print("error:", p["handle"], res["userErrors"])
        return 1
    sku_to_id = {v["sku"]: v["id"] for v in res["productVariants"]}
    errs = s.gql(UPDATE_M, {"i": {"id": prod["id"]}, "m": media})["productUpdate"]["userErrors"]
    if errs:
        print("update error:", p["handle"], errs)
        return 1
    by_alt = wait_media(prod["id"], [f["alt"] for f in files])
    errors += link_photos(p, prod["id"], new, sku_to_id, by_alt)
    return errors


PUBLICATION = os.environ.get("ONLINE_STORE_PUBLICATION", "gid://shopify/Publication/338148819125")  # Online Store channel
STATE_Q = """query($q:String!){ products(first:5, query:$q){ nodes{ id handle status } } }"""
PUBLISH_M = """mutation($id:ID!,$p:ID!){ publishablePublish(id:$id, input:[{publicationId:$p}]){ userErrors{ field message } } }"""


def publish(dry):
    """Puts on the Online Store channel the products of the selection that the targeted check made ACTIVE (idempotent)."""
    selection = json.load(open(os.path.join(HERE, "amz", "selection.json"), encoding="utf-8"))
    done = 0
    for p in selection:
        handle = p.get("extend") or p["handle"]
        found = [x for x in s.gql(STATE_Q, {"q": f"handle:{handle}"})["products"]["nodes"] if x["handle"] == handle]
        if not found:
            print("not in the shop:", handle)
            continue
        if found[0]["status"] != "ACTIVE":
            print("stays hidden (draft, nothing sellable now):", handle)
            continue
        print(("DRY RUN: would publish " if dry else "publishing ") + handle)
        if not dry:
            errs = s.gql(PUBLISH_M, {"id": found[0]["id"], "p": PUBLICATION})["publishablePublish"]["userErrors"]
            if errs:
                print("error:", handle, errs)
            else:
                done += 1
    print(f"{done} products published.")


def main():
    if not s.have_credentials():
        return
    if not s.AED_TO_FDJ:
        sys.exit("ALERTE: PRICE_FORMULA is not set.")
    dry = os.environ.get("DRY_RUN") == "1"
    if len(sys.argv) > 1 and sys.argv[1] == "publish":
        return publish(dry)
    only = set(filter(None, os.environ.get("ONLY_HANDLES", "").split(",")))
    selection = json.load(open(os.path.join(HERE, "amz", "selection.json"), encoding="utf-8"))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    made, errors, asins = 0, 0, []
    for p in selection:
        if only and p["handle"] not in only:
            continue
        handle = p.get("extend") or p["handle"]
        found = s.gql(FIND_Q, {"q": f"handle:{handle}"})["products"]["nodes"]
        found = [x for x in found if x["handle"] == handle]
        asins += [v["asin"] for v in p["variants"]]
        if p.get("extend"):
            if not found:
                print("extend target not found:", handle)
                errors += 1
                continue
            errors += extend(p, found[0], now, dry)
            continue
        if found:
            print("already exists:", p["handle"])
            continue
        print(("DRY RUN: would create " if dry else "creating ") + f"{p['handle']} ({len(p['variants'])} variants, "
              f"{min(s.formula(v['aed'], p['weight_g']) for v in p['variants'])}-"
              f"{max(s.formula(v['aed'], p['weight_g']) for v in p['variants'])} Fdj)")
        if dry:
            continue
        try:
            files = [photo_file(p, v) for v in p["variants"]]
        except Exception as e:  # noqa: BLE001
            print("photo error:", p["handle"], f"{type(e).__name__}: {e}"[:150])
            errors += 1
            continue
        inp = {
            "title": p["title"], "handle": p["handle"], "vendor": p["vendor"], "productType": p.get("product_type", PRODUCT_TYPE),
            "status": "DRAFT",
            "tags": tags_of(p), "descriptionHtml": html(p),
            "seo": {"title": p.get("seo_title") or p["title"][:60], "description": p["seo_desc"]},
            "productOptions": [{"name": p.get("option", "Teinte"), "values": [{"name": v["label"]} for v in p["variants"]]}],
            "variants": [variant_input(p, v, now) for v in p["variants"]], "files": files,
            "metafields": [
                {"namespace": "internal", "key": "supplier", "type": "single_line_text_field", "value": "Amazon.ae"},
                {"namespace": "internal", "key": "supplier_ref", "type": "single_line_text_field", "value": f"ASIN {p['variants'][0]['asin']}"},
                {"namespace": "internal", "key": "cost_aed", "type": "number_decimal", "value": f"{p['variants'][0]['aed']:.2f}"},
                {"namespace": "internal", "key": "weight_g", "type": "number_integer", "value": str(p["weight_g"])},
                {"namespace": "global", "key": "description_tag", "type": "string", "value": p["seo_desc"]}]}
        res = s.gql(SET_M, {"input": inp})["productSet"]
        if res["userErrors"]:
            errors += 1
            print("error:", p["handle"], res["userErrors"])
            continue
        made += 1
        prod = res["product"]
        by_alt = wait_media(prod["id"], [f["alt"] for f in files])
        errors += link_photos(p, prod["id"], p["variants"], {v["sku"]: v["id"] for v in prod["variants"]["nodes"]}, by_alt)
    print(f"{made} products created, {errors} errors.")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"asins={','.join(dict.fromkeys(asins))}\n")
    if errors and not dry:
        sys.exit(f"ALERTE: {errors} errors while creating Amazon.ae makeup products.")


if __name__ == "__main__":
    main()
