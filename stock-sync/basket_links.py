#!/usr/bin/env python3
"""One-tap Amazon.ae basket links for paid orders. No login, no purchase: the owner opens the link on a phone
where she is already signed in to Amazon, checks the basket and pays herself.

  python3 -I basket_links.py list [ORDER_NAME ...]   print the basket link of the given orders (or the recent paid ones)
  python3 -I basket_links.py note [ORDER_NAME ...]   same, and write the link in the order note (Shopify admin app)
"""
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import amazon_sync as s  # noqa: E402
from order_check import asin_of  # noqa: E402

CART = "https://www.amazon.ae/gp/aws/cart/add.html"  # Amazon's standard multi-item add-to-cart URL
Q = """query($q:String!){ orders(first:25, query:$q, sortKey:CREATED_AT){ nodes{ id name note
  lineItems(first:50){ nodes{ title variantTitle sku quantity
    variant{ id product{ id handle vendor
      ref: metafield(namespace:"internal", key:"supplier_ref"){value}
      spreadr: metafield(namespace:"global", key:"spreadr-asin"){value}
      variantsCount{ count } } } } } } } }"""
NOTE_M = "mutation($i:OrderInput!){orderUpdate(input:$i){userErrors{field message}}}"


def basket(items):
    """-> (url or None, [labels without ASIN]). Same ASIN is merged;."""
    qty, missing = {}, []
    for it in items:
        a = asin_of(it)
        label = it["title"] + (f" ({it['variantTitle']})" if it.get("variantTitle") else "")
        if a:
            qty[a] = qty.get(a, 0) + it["quantity"]
        else:
            missing.append(label)
    if not qty:
        return None, missing
    params = []
    for n, (a, q) in enumerate(qty.items(), 1):
        params += [(f"ASIN.{n}", a), (f"Quantity.{n}", q)]
    return CART + "?" + urllib.parse.urlencode(params), missing


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "list"
    names = [n.lstrip("#") for n in sys.argv[2:]]
    q = " OR ".join(f"name:{n}" for n in names) if names else "financial_status:paid -status:cancelled -fulfillment_status:shipped"
    for o in s.gql(Q, {"q": q})["orders"]["nodes"]:
        url, missing = basket(o["lineItems"]["nodes"])
        print(f"{o['name']}: {url or 'no Amazon item'}")
        for m in missing:
            print(f"   no ASIN, order by hand: {m}")
        if mode == "note" and url and "amazon.ae/gp/aws/cart" not in (o.get("note") or ""):
            text = ((o.get("note") or "") + f"\nPanier Amazon.ae : {url}").strip()
            errs = s.gql(NOTE_M, {"i": {"id": o["id"], "note": text}})["orderUpdate"]["userErrors"]
            print("   note error:" if errs else "   note written", errs or "")


if __name__ == "__main__":
    main()
