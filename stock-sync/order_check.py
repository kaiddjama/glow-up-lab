#!/usr/bin/env python3
"""Checks on Amazon.ae, right after an order arrives, that every item ordered can still be bought there.

  python3 -I order_check.py list    counts the recent orders not checked yet (also to $GITHUB_OUTPUT: count)
  python3 -I order_check.py check   reads the Amazon.ae page of every item of those orders (browser set to Dubai):
                                    - all items sellable: the order gets the tag amazon-ok
                                    - an item not sellable (or with no ASIN): the order gets the tag amazon-ko, the
                                      variant goes to Épuisé, and alert.md describes it for the owner
                                    - a page that could not be read: the order is left alone and tried again at the next
                                      run, until it is ORDER_MAX_AGE_H old (then amazon-incertain)
Needs the app scopes read_orders and write_orders. DRY_RUN=1 reports only.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I does not add the script folder
import amazon_sync as s  # noqa: E402

WINDOW_H = 6  # orders newer than this are looked at
ORDER_MAX_AGE_H = 2  # an order whose pages still cannot be read after this long is tagged amazon-incertain

Q = """query($q:String!){ orders(first:25, query:$q, sortKey:CREATED_AT){ nodes{
  id name createdAt tags
  lineItems(first:50){ nodes{ title variantTitle sku quantity
    variant{ id inventoryPolicy
      product{ id handle vendor
        ref: metafield(namespace:"internal", key:"supplier_ref"){value}
        spreadr: metafield(namespace:"global", key:"spreadr-asin"){value}
        variantsCount{ count } } } } } } } }"""
TAGS_ADD_ORDER_M = """mutation($id:ID!,$t:[String!]!){tagsAdd(id:$id, tags:$t){userErrors{field message}}}"""


def recent_orders():
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=WINDOW_H)).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = f"created_at:>={since} -tag:amazon-ok -tag:amazon-ko -tag:amazon-incertain -status:cancelled"
    return s.gql(Q, {"q": q})["orders"]["nodes"]


def asin_of(item):
    v = item.get("variant")
    if not v:
        return None
    m = s.ASIN_RE.search(item.get("sku") or "")
    if m:
        return m.group(1)
    p = v["product"]
    if p["variantsCount"]["count"] == 1:
        for src in (p.get("spreadr"), p.get("ref")):
            m = src and s.ASIN_RE.search(src["value"])
            if m:
                return m.group(1)
    return None


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "list"
    if not (os.environ.get("SHOPIFY_STORE") and (os.environ.get("SHOPIFY_TOKEN") or os.environ.get("SHOPIFY_CLIENT_SECRET"))):
        print("No Shopify credentials set: nothing to do.")
        return
    orders = recent_orders()
    if mode == "list":
        print(f"{len(orders)} recent orders to check.")
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a") as f:
                f.write(f"count={len(orders)}\n")
        return
    dry = os.environ.get("DRY_RUN") == "1"
    today = dt.date.today()
    now = dt.datetime.now(dt.timezone.utc)
    import browser_fetch
    reader = browser_fetch.BrowserReader().start()
    print("Browser reader started, delivery location:", reader.location_text())
    pages, alerts = {}, []

    def page_of(asin):
        if asin not in pages:
            try:
                pages[asin] = s.parse(reader.get(f"https://www.amazon.ae/dp/{asin}?language=en_AE"), today)
            except Exception as e:  # LocationLost, timeouts...
                pages[asin] = {"error": type(e).__name__}
        return pages[asin]

    try:
        for o in orders:
            bad, unknown = [], []
            for it in o["lineItems"]["nodes"]:
                label = f"{it['title']}" + (f" ({it['variantTitle']})" if it.get("variantTitle") else "")
                asin = asin_of(it)
                if not asin:
                    bad.append((it, label, "pas de code ASIN, impossible à vérifier"))
                    continue
                pg = page_of(asin)
                if pg.get("error"):
                    unknown.append(label)
                elif not s.sellable(pg, {"vendor": it["variant"]["product"]["vendor"] or ""}):
                    why = ("pas en stock sur Amazon.ae" if not pg["inStock"] else
                           f"livraison trop lente ({pg.get('deliveryText')})")
                    bad.append((it, label, why))
            age_h = (now - dt.datetime.fromisoformat(o["createdAt"].replace("Z", "+00:00"))).total_seconds() / 3600
            if bad:
                tag = "amazon-ko"
            elif unknown and age_h < ORDER_MAX_AGE_H:
                print(f"{o['name']}: {len(unknown)} page(s) not read, will try again.")
                continue
            elif unknown:
                tag = "amazon-incertain"
            else:
                tag = "amazon-ok"
            print(f"{o['name']}: {tag}")
            for it, label, why in bad:
                print(f"  indisponible: {label} - {why}")
                alerts.append(f"- Commande {o['name']}: **{label}** : {why}")
            if tag == "amazon-incertain":
                alerts.append(f"- Commande {o['name']}: pages Amazon illisibles pour {', '.join(unknown)} : à vérifier à la main")
            if dry:
                continue
            errs = s.gql(TAGS_ADD_ORDER_M, {"id": o["id"], "t": [tag]})["tagsAdd"]["userErrors"]
            if errs:
                print("tag error:", errs)
            by_product = {}
            for it, _, _ in bad:
                v = it.get("variant")
                if v and v["inventoryPolicy"] == "CONTINUE":
                    by_product.setdefault(v["product"]["id"], []).append({"id": v["id"], "inventoryPolicy": "DENY"})
            for pid, ups in by_product.items():
                errs = s.gql(s.PRICES_M, {"p": pid, "v": ups})["productVariantsBulkUpdate"]["userErrors"]
                if errs:
                    print("variant error:", errs)
    finally:
        reader.close()
    if alerts:
        with open("alert.md", "w") as f:
            f.write("Articles commandés non disponibles sur Amazon.ae :\n\n" + "\n".join(alerts) + "\n")
        print("\n".join(alerts))


if __name__ == "__main__":
    main()
