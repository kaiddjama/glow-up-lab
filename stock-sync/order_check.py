#!/usr/bin/env python3
"""Checks on Amazon.ae, right after an order arrives, that every item ordered can still be bought there.

  python3 -I order_check.py list    counts the recent orders not checked yet (also to $GITHUB_OUTPUT: count)
  python3 -I order_check.py check   reads the Amazon.ae page of every item of those orders (browser set to Dubai; items with a
                                    SKU "MEDX-..." are read on medxpharmacy.com instead, stock at least MEDX_MIN_QTY, and
                                    items with a SKU "PSAE-..." on padelshop.ae, which must say available):
                                    - all items sellable: the order gets the tag amazon-ok
                                    - an item not sellable (or with no ASIN): the page is read a second time first (a
                                      serious verdict is checked twice); then the order gets the tag amazon-ko, the
                                      variant goes to Épuisé, and alert.md describes it for the owner with what the page
                                      showed (seller, stock, every delivery date). When the reason is about STOCK (out
                                      of stock, tiny stock, listing removed or replaced) the variant stays Épuisé for
                                      COOL_HOURS: the robot may still read it "available" while it is not. When it is
                                      about the DATE, the next stock check decides (no cool-down): order #1048 hid six
                                      good variants for a day on an evening date
                                    - the same rule as the stock check decides, evening slack included (the item was on
                                      sale when the customer ordered it)
                                    - an Amazon.ae item that cannot be bought there but can at its second source
                                      (supplier.fallback): the order is fine, alert.md says where to buy it (tag source-2)
                                    - more units ordered than Amazon.ae shows or allows per order: tag amazon-qte, a
                                      line in alert.md, nothing hidden
                                    - a page that could not be read: the order is left alone and tried again at the next
                                      run, until it is ORDER_MAX_AGE_H old (then amazon-incertain)
An order stays in the list until it carries one of these tags, for WINDOW_H hours: a check that was down for a night
catches up by itself. One order that cannot be handled never stops the others.
Needs the app scopes read_orders and write_orders. DRY_RUN=1 reports only.
"""
import datetime as dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I does not add the script folder
import amazon_sync as s  # noqa: E402
import medx  # noqa: E402
import padelshop  # noqa: E402
import suppliers  # noqa: E402

WINDOW_H = 72  # orders newer than this and not tagged yet are looked at
ORDER_MAX_AGE_H = 2  # an order whose pages still cannot be read after this long is tagged amazon-incertain
COOL_HOURS = 24  # a variant an order proved unavailable is not put back on sale by the sync before this long

Q = """query($q:String!,$after:String){ orders(first:20, after:$after, query:$q, sortKey:CREATED_AT){
  pageInfo{hasNextPage endCursor}
  nodes{ id name createdAt tags
  lineItems(first:50){ nodes{ title variantTitle sku quantity
    variant{ id inventoryPolicy
      state: metafield(namespace:"supplier", key:"sync_state"){value}
      fallback: metafield(namespace:"supplier", key:"fallback"){value}
      product{ id handle vendor isGiftCard
        ref: metafield(namespace:"internal", key:"supplier_ref"){value}
        spreadr: metafield(namespace:"global", key:"spreadr-asin"){value}
        variantsCount{ count } } } } } } } }"""
TAGS_ADD_ORDER_M = """mutation($id:ID!,$t:[String!]!){tagsAdd(id:$id, tags:$t){userErrors{field message}}}"""


def recent_orders():
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=WINDOW_H)).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = f"created_at:>={since} -tag:amazon-ok -tag:amazon-ko -tag:amazon-incertain -status:cancelled"
    orders, after = [], None
    while True:
        data = s.gql(Q, {"q": q, "after": after})["orders"]
        orders += data["nodes"]
        if not data["pageInfo"]["hasNextPage"]:
            return orders
        after = data["pageInfo"]["endCursor"]


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


def seen(pg):
    """What the page showed, so the owner can compare with her own account without asking."""
    bits = [f"vendeur {pg['seller']}" if pg.get("seller") else "",
            "expédié par Amazon" if pg.get("amazonShips") else "",
            f"dates affichées : {pg['promises']}" if pg.get("promises") else ""]
    bits = [b for b in bits if b]
    return f" [lu à {pg['hour']} h à Dubaï : {' ; '.join(bits)}]" if bits and pg.get("hour") is not None else ""


def why_not(pg):
    """(in French, for the owner: why this Amazon.ae page cannot be bought now; is the reason about stock?).
    A stock reason keeps the variant Épuisé for COOL_HOURS; a date reason is left to the next stock check."""
    if pg.get("gone"):
        return "fiche supprimée sur Amazon.ae", True
    if pg.get("redirect"):
        return f"Amazon.ae affiche maintenant un autre article ({pg['redirect']}) à cette adresse", True
    if pg.get("amazonNow"):
        # same decision as out of stock (no ordinary offer to order), but the owner is told what the page really shows
        return ("plus d'offre ordinaire sur Amazon.ae, l'article n'est proposé qu'en Amazon Now (livraison en quelques "
                "minutes à Dubaï, panier à part)" + seen(pg)), True
    if not pg.get("inStock"):
        return "pas en stock sur Amazon.ae" + seen(pg), True
    if s.low_stock(pg):
        return (f"stock très faible sur Amazon.ae ({pg['stockLeft']} restant(s)) : l'offre peut passer à un vendeur lent, "
                "vérifie le délai sur ton compte et achète vite" + seen(pg)), True
    if pg.get("sourceDays") is None:
        return "en stock mais sans date de livraison pour Dubaï" + seen(pg), False
    return (f"livraison trop lente ({pg.get('deliveryText')}, soit {pg['sourceDays']} jours jusqu'à Dubaï) : "
            "vérifie sur ton compte, la variante revient seule en vente si le délai redevient bon" + seen(pg)), False


def quantity_note(pg, wanted):
    """A warning when more units were ordered than Amazon.ae shows in stock or allows in one order, else None."""
    left, most = pg.get("stockLeft"), pg.get("maxQty")
    if left is not None and wanted > left:
        return f"{wanted} commandés, {left} restant(s) sur Amazon.ae"
    if most is not None and wanted > most:
        return f"{wanted} commandés, Amazon.ae en laisse acheter {most} par commande"
    return None


def other_source(pages, ref):
    """(page, module, display name) of a MEDX-/PSAE- reference, read once per run."""
    mod, slug, name = suppliers.module_of(ref)
    if not mod:
        return None, None, None
    if ref not in pages:
        pages[ref] = mod.fetch(slug)
    return pages[ref], mod, name


def check_item(it, amazon_page_of, other_pages):
    """("ok" | "ko" | "unknown", reason or None, notes, cool). notes = [(tag, text)] to tell the owner without blocking;
    cool = the variant must stay Épuisé for COOL_HOURS (a stock reason). amazon_page_of(asin, again=False) reads a page
    (again=True: a fresh reading)."""
    for mod, name in ((medx, "MedX"), (padelshop, "PadelShop.ae")):
        if mod.slug_of(it.get("sku")):
            pg, _, _ = other_source(other_pages, it["sku"].strip())
            if pg.get("error"):
                return "unknown", None, [], False
            if mod.sellable(pg, True):
                return "ok", None, [], False
            if pg.get("gone"):
                return "ko", f"fiche retirée chez {name}", [], False
            if mod is medx:
                return "ko", (f"stock MedX insuffisant ({pg['qty']} restant)" if pg["publish"] else "fiche MedX non publiée"), [], False
            return "ko", f"plus disponible chez {name}", [], False
    asin = asin_of(it)
    if not asin:
        return "ko", "pas de code ASIN, impossible à vérifier", [], False
    pg = amazon_page_of(asin)
    if pg.get("error"):
        return "unknown", None, [], False
    pg, ok = s.offer_for(pg, True)  # the item was on sale when it was ordered: same rule as the stock check
    if not ok:  # a serious verdict is checked twice: a second, fresh reading
        again = amazon_page_of(asin, True)
        if not again.get("error"):
            pg, ok = s.offer_for(again, True)
    if ok:
        note = quantity_note(pg, it.get("quantity") or 1)
        return "ok", None, [("amazon-qte", note)] if note else [], False
    why, cool = why_not(pg)
    ref = ((it["variant"].get("fallback") or {}).get("value") or "").strip()
    if ref:  # Amazon.ae cannot sell it: is the second source able to?
        other, mod, name = other_source(other_pages, ref)
        if mod and other.get("error"):
            return "unknown", None, [], False
        if mod and mod.sellable(other, True):
            return "ok", None, [("source-2", f"à acheter chez {name} ({ref}) : {why}")], False
    return "ko", why, [], cool


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "list"
    if not s.have_credentials():
        return
    try:
        orders = recent_orders()
    except RuntimeError as e:
        if "ACCESS_DENIED" not in str(e):
            raise
        # The Shopify app has no read_orders scope: this used to be a quiet warning; without it no order is checked at all.
        sys.exit("ALERTE: the Shopify app lacks the read_orders / write_orders access scopes: no order can be checked. "
                 "Add them to the app and approve the update.")
    if mode == "list":
        print(f"{len(orders)} recent orders to check.")
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a") as f:
                f.write(f"count={len(orders)}\n")
        return
    dry = os.environ.get("DRY_RUN") == "1"
    now = dt.datetime.now(dt.timezone.utc)
    pages, other_pages, alerts, problems = {}, {}, [], 0
    browser = {"tried": False}

    def page_of(asin, again=False):
        if again and s.READER and not pages.get(asin, {}).get("error"):
            time.sleep(6)
            pages.pop(asin, None)
        if asin not in pages:
            if not browser["tried"]:  # started only when an Amazon.ae item has to be read
                browser["tried"] = True
                try:
                    s.start_browser()
                except SystemExit as e:
                    print(e)
            if not s.READER:
                pages[asin] = {"error": "browser not started"}
            else:
                try:
                    pages[asin] = s.read_page(asin)
                except Exception as e:  # LocationLost, timeouts...
                    pages[asin] = {"error": type(e).__name__}
        return pages[asin]

    try:
        for o in orders:
            try:
                bad, unknown, notes = [], [], []
                for it in o["lineItems"]["nodes"]:
                    if (it.get("variant") or {}).get("product", {}).get("isGiftCard"):
                        continue  # gift card: nothing to buy
                    label = f"{it['title']}" + (f" ({it['variantTitle']})" if it.get("variantTitle") else "")
                    if not it.get("variant"):
                        bad.append((it, label, "article sans fiche dans la boutique (supprimée ?), impossible à vérifier", False))
                        continue
                    verdict, why, extra, cool_it = check_item(it, page_of, other_pages)
                    notes += [(tag, f"{label} : {text}") for tag, text in extra]
                    if verdict == "ko":
                        bad.append((it, label, why, cool_it))
                    elif verdict == "unknown":
                        unknown.append(label)
                age_h = s.hours_since(o["createdAt"], now)
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
                for it, label, why, _ in bad:
                    print(f"  indisponible: {label} - {why}")
                    alerts.append(f"- Commande {o['name']}: **{label}** : {why}")
                if tag == "amazon-incertain":
                    alerts.append(f"- Commande {o['name']}: pages illisibles pour {', '.join(unknown)} : à vérifier à la main")
                for _, text in notes:
                    print(f"  note: {text}")
                    alerts.append(f"- Commande {o['name']}: {text}")
                if dry:
                    continue
                tags = [tag] + sorted({t for t, _ in notes})
                errs = s.gql(TAGS_ADD_ORDER_M, {"id": o["id"], "t": tags})["tagsAdd"]["userErrors"]
                if errs:
                    problems += 1
                    print("tag error:", errs)
                by_product, cool = {}, []
                until = s.iso(now + dt.timedelta(hours=COOL_HOURS))
                for it, _, _, cool_it in bad:
                    v = it.get("variant")
                    if not v:
                        continue
                    if v["inventoryPolicy"] == "CONTINUE":
                        by_product.setdefault(v["product"]["id"], []).append({"id": v["id"], "inventoryPolicy": "DENY"})
                    if cool_it and asin_of(it) and not suppliers.is_other_source(it.get("sku")):
                        state = {**s.read_state(v.get("state")), "cool": until}
                        state.pop("src", None)
                        state.pop("src_t", None)
                        cool.append(s.field(v["id"], "sync_state", "json", json.dumps(state, separators=(",", ":"))))
                for pid, ups in by_product.items():
                    errs = s.gql(s.PRICES_M, {"p": pid, "v": ups})["productVariantsBulkUpdate"]["userErrors"]
                    if errs:
                        problems += 1
                        print("variant error:", errs)
                if cool:
                    errs = s.gql(s.META_M, {"m": cool})["metafieldsSet"]["userErrors"]
                    if errs:
                        print("cool-down error:", errs)
            except Exception as e:  # one order that cannot be handled must not stop the others
                problems += 1
                print(f"::warning::{o.get('name')}: not checked ({type(e).__name__}: {str(e)[:150]}), tried again at the next run")
    finally:
        if s.READER:
            s.READER.close()
    if alerts:
        with open("alert.md", "w") as f:
            f.write("Commandes à regarder (Amazon.ae, MedX ou PadelShop.ae) :\n\n" + "\n".join(alerts) + "\n")
        print("\n".join(alerts))
    if problems and not dry:
        sys.exit(f"ALERTE: {problems} order(s) could not be checked or tagged completely; see the log.")


if __name__ == "__main__":
    main()
