#!/usr/bin/env python3
"""Links Shopify variants to their Amazon.ae pages (ASIN) and lists variants that exist on Amazon.ae but not in Shopify.

  python3 -I variant_map.py probe ASIN [ASIN ...]   prints what the Amazon.ae page says about its variants (twister data)
  python3 -I variant_map.py report                  reads one sibling page of every multi-variant product that has
                                                    variants without an ASIN, writes variant-map.json and prints it
  python3 -I variant_map.py apply map.json          writes the SKU "AMZ-<ASIN>" on the variants listed in map.json
                                                    ({"<variant gid>": "<ASIN>"}); DRY_RUN=1 reports only

The ASIN of a variant is what amazon_sync.py needs to check its stock and price; a variant without one is kept on
Épuisé by unmapped_guard.py. Needs the same environment as amazon_sync.py (and FETCHER=browser for probe/report).
"""
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I does not add the script folder
import amazon_sync as s  # noqa: E402

Q = """query($after:String){ products(first:40, after:$after, query:"status:active"){
  pageInfo{hasNextPage endCursor}
  nodes{ id handle title
    ref: metafield(namespace:"internal", key:"supplier_ref"){value}
    spreadr: metafield(namespace:"global", key:"spreadr-asin"){value}
    variants(first:100){ nodes{ id title sku inventoryPolicy } } } } }"""
SKU_M = """mutation($p:ID!,$v:[ProductVariantsBulkInput!]!){
  productVariantsBulkUpdate(productId:$p, variants:$v){userErrors{field message}}}"""
VARIANT_Q = """query($id:ID!){ productVariant(id:$id){ id product{ id } } }"""


def products():
    after = None
    while True:
        data = s.gql(Q, {"after": after})["products"]
        yield from data["nodes"]
        if not data["pageInfo"]["hasNextPage"]:
            return
        after = data["pageInfo"]["endCursor"]


def json_after(html, key):
    """The JSON object or array that follows "key": in the page source, or None."""
    m = re.search(r'"%s"\s*:\s*' % re.escape(key), html)
    if not m:
        return None
    i = m.end()
    if i >= len(html) or html[i] not in "{[":
        return None
    open_c, close_c = html[i], "}" if html[i] == "{" else "]"
    depth, j, in_str, esc = 0, i, False, False
    while j < len(html):
        c = html[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[i:j + 1])
                except ValueError:
                    return None
        j += 1
    return None


def twister(html):
    """{ASIN: label} for every variant the Amazon.ae page offers (label = its dimension values joined with ' / ')."""
    out = {}
    disp = json_after(html, "dimensionValuesDisplayData")
    if isinstance(disp, dict):
        for asin, vals in disp.items():
            out[asin] = " / ".join(str(v) for v in (vals if isinstance(vals, list) else [vals]))
        return out
    asv, vv = json_after(html, "asinVariationValues"), json_after(html, "variationValues")
    if isinstance(asv, dict) and isinstance(vv, dict):
        for asin, idx in asv.items():
            labels = []
            for dim, i in idx.items():
                try:
                    labels.append(str(vv[dim][int(i)]))
                except (KeyError, ValueError, IndexError, TypeError):
                    labels.append(f"{dim}={i}")
            out[asin] = " / ".join(labels)
    return out


def reader():
    import browser_fetch
    r = browser_fetch.BrowserReader().start()
    print("Browser reader started, delivery location:", r.location_text())
    return r


def probe(asins):
    r = reader()
    try:
        for a in asins:
            html = r.get(f"https://www.amazon.ae/dp/{a}?language=en_AE")
            print(f"\n=== {a}: {len(html)} bytes")
            for key in ("dimensionValuesDisplayData", "asinVariationValues", "variationValues", "dimensionToAsinMap",
                        "twisterData", "dimensions", "parentAsin"):
                k = html.find('"%s"' % key)
                print(f"  key {key}: {'found at ' + str(k) if k >= 0 else 'absent'}")
            tw = twister(html)
            print(f"  twister: {len(tw)} variants")
            for asin, label in list(tw.items())[:60]:
                print(f"    {asin}  {label}")
            if not tw:
                k = html.find("twister")
                print("  context:", re.sub(r"\s+", " ", html[max(0, k - 200):k + 1200]) if k >= 0 else "no 'twister' in page")
    finally:
        r.close()


def report():
    todo = []
    for p in products():
        vs = p["variants"]["nodes"]
        asin_of = {v["id"]: (s.ASIN_RE.search(v.get("sku") or "") or [None, None])[1] for v in vs}
        missing = [v for v in vs if not asin_of[v["id"]]]
        pasin = None
        for src in (p.get("spreadr"), p.get("ref")):
            m = src and s.ASIN_RE.search(src["value"])
            if m:
                pasin = m.group(1)
                break
        if len(vs) == 1:
            if not asin_of[vs[0]["id"]] and not pasin:
                todo.append({"handle": p["handle"], "single": True, "missing": [vs[0]], "known": {}, "sibling": None})
            continue
        known = {a: v["title"] for v in vs for a in [asin_of[v["id"]]] if a}
        sibling = next(iter(known), None) or pasin
        if missing or True:  # also products whose variants all have an ASIN: Amazon may offer more variants
            todo.append({"handle": p["handle"], "single": False, "missing": missing, "known": known,
                         "sibling": sibling, "all": vs})
    r = reader()
    result = []
    try:
        for t in todo:
            if t["single"]:
                result.append({"handle": t["handle"], "single_without_asin": True,
                               "variantId": t["missing"][0]["id"], "title": t["missing"][0]["title"]})
                continue
            if not t["sibling"]:
                result.append({"handle": t["handle"], "no_sibling_page": True,
                               "missing": [{"id": v["id"], "title": v["title"]} for v in t["missing"]]})
                continue
            try:
                tw = twister(r.get(f"https://www.amazon.ae/dp/{t['sibling']}?language=en_AE"))
            except Exception as e:  # LocationLost, timeouts...
                result.append({"handle": t["handle"], "error": type(e).__name__})
                continue
            new_on_amazon = {a: l for a, l in tw.items() if a not in t["known"]}
            result.append({"handle": t["handle"], "sibling": t["sibling"], "amazon_variants": len(tw),
                           "known": t["known"],
                           "missing": [{"id": v["id"], "title": v["title"], "policy": v["inventoryPolicy"]}
                                       for v in t["missing"]],
                           "amazon_not_in_shopify": new_on_amazon})
    finally:
        r.close()
    with open("variant-map.json", "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    n_missing = sum(len(x.get("missing", [])) for x in result)
    print(f"{len(result)} products looked at, {n_missing} variants without ASIN")
    for x in result:
        if x.get("missing") or x.get("amazon_not_in_shopify") or x.get("error"):
            print(json.dumps(x, ensure_ascii=False))


def apply(path):
    mapping = json.load(open(path))
    dry = os.environ.get("DRY_RUN") == "1"
    by_product = {}
    for vid, asin in mapping.items():
        if not re.fullmatch(r"B0[A-Z0-9]{8}", asin):
            print("skip (bad ASIN):", vid, asin)
            continue
        pid = s.gql(VARIANT_Q, {"id": vid})["productVariant"]["product"]["id"]
        by_product.setdefault(pid, []).append({"id": vid, "inventoryItem": {"sku": f"AMZ-{asin}"}})
    n = sum(len(v) for v in by_product.values())
    print(f"{n} variants get an ASIN in their SKU" + (" (dry run)" if dry else ""))
    if dry:
        return
    for pid, ups in by_product.items():
        errs = s.gql(SKU_M, {"p": pid, "v": ups})["productVariantsBulkUpdate"]["userErrors"]
        for e in errs:
            print("error:", pid, e)


def main():
    if not (os.environ.get("SHOPIFY_STORE") and (os.environ.get("SHOPIFY_TOKEN") or os.environ.get("SHOPIFY_CLIENT_SECRET"))):
        print("No Shopify credentials set: nothing to do.")
        return
    mode = sys.argv[1] if len(sys.argv) > 1 else "report"
    if mode == "probe":
        probe(sys.argv[2:])
    elif mode == "report":
        report()
    elif mode == "apply":
        apply(sys.argv[2])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
