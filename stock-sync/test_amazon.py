#!/usr/bin/env python3
"""Offline tests of the Amazon.ae page reading (amazon_page.py) and of the stock decisions (amazon_sync.plan).
Run: python3 -I test_amazon.py   (no network, no Shopify). The pages are small skeletons carrying the same markers as
the real pages studied on 10 and 11 Nov (ids of the buy box, delivery tags, identity markers, who ships the offer)."""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.pop("PRICE_FORMULA", None)
import amazon_page as ap  # noqa: E402
import amazon_sync as s  # noqa: E402
import order_check as oc  # noqa: E402
import suppliers  # noqa: E402

TODAY = dt.date(2026, 11, 10)
NOW = dt.datetime(2026, 11, 10, 9, 0, tzinfo=dt.timezone.utc)
s.MARGIN_CUSTOMS, s.SHIPPING_AED_PER_KG, s.AED_TO_FDJ = 2.0, 10.0, 50.0  # test values, not the real formula


def delivery(when, price="FREE", mir="", program=""):
    return (f'<span data-csa-c-type="element" data-csa-c-delivery-price="{price}" data-csa-c-mir-type="{mir}" '
            f'data-csa-c-delivery-benefit-program-id="{program}" data-csa-c-delivery-time="{when}">x</span>')


def feature(name, label, value):
    """One line of the offer's "seller, shipping and buying option details" box, as on the real pages (the id is repeated
    as data-csa-c-slot-id inside the tag, which once cut the reading short)."""
    return (f'<div id="{name}_feature_div" class="celwidget" data-csa-c-slot-id="{name}_feature_div">'
            + (f'<span class="a-size-small a-color-tertiary">{label}</span><span class="a-size-small '
               f'offer-display-feature-text-message">{value}</span>' if label else "") + "</div>")


def shipping(seller, ships):
    """ships: "fba" = Fulfilled by Amazon (another seller's stock in Amazon's warehouse), "amazon" = Shipper / Seller
    Amazon.ae, "easyship" = Delivered by Amazon.ae (the seller hands the parcel over), "seller" = shipped by the seller."""
    if ships == "amazon":
        return feature("fulfillerInfoFeature", "", "") + feature("merchantInfoFeature", "Shipper / Seller", "Amazon.ae")
    if ships == "fba":
        return feature("fulfillerInfoFeature", "Fulfilled by", "Amazon") + feature("merchantInfoFeature", "Sold by", seller)
    if ships == "easyship":
        return feature("fulfillerInfoFeature", "Delivered by", "Amazon.ae") + feature("merchantInfoFeature", "Sold by", seller)
    return feature("fulfillerInfoFeature", "", "") + feature("merchantInfoFeature", "Shipper / Seller", seller)


def offer(price="54.00", avail="In Stock", deliveries=(), seller="Padimu", cart=True, qty=10, ships="seller"):
    whole, frac = (price.split(".") + ["00"])[:2] if price else ("", "")
    return "".join([
        shipping(seller, ships),
        f'<div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">AED&nbsp;{price}</span>'
        f'<span class="a-price-whole">{whole}</span><span class="a-price-fraction">{frac}</span></span></div>' if price else "",
        "".join(deliveries),
        f'<div id="availability" class="a-section"> <span> {avail} </span> <script>{{"isInternal":false}}</script></div>',
        '<select name="quantity" id="quantity">' + "".join(f'<option value="{n}">{n}</option>' for n in range(1, qty + 1))
        + "</select>",
        '<input id="add-to-cart-button" type="submit">' if cart else "",
        f'<a id="sellerProfileTriggerId" href="#">{seller}</a>' if seller else ""])


def page(asin="B0AAAAAAAA", offers=None, city="Dubai, Ras Al Khor", shown=None, variation="Warm"):
    shown = shown or asin
    offers = offers if offers is not None else [offer(deliveries=[delivery("Tomorrow, 11 November")])]
    if len(offers) == 1:
        box = '<div id="qualifiedBuybox">' + offers[0] + "</div>"
    else:
        box = '<div id="buyBoxAccordion">' + "".join(
            f'<div id="newAccordionRow_{k}">{o}</div>' for k, o in enumerate(offers)) + '<div id="almAccordionRow"></div></div>'
    return (f'<html><head><link rel="canonical" href="https://www.amazon.ae/x/dp/{shown}"></head><body>'
            f'<span id="glow-ingress-line2"> {city}</span><span id="productTitle"> e.l.f. Camo Concealer </span>'
            f'<input type="hidden" id="ASIN" name="ASIN" value="{shown}"><script>{{"currentAsin" : "{shown}"}}</script>'
            f'<span id="inline-twister-expanded-dimension-text-color_name">{variation}</span>'
            f'<div id="desktop_buybox">{box}</div><div id="wishlistButtonStack"></div>'
            '<div id="corePrice_feature_div"><span class="a-offscreen">AED&nbsp;1.00</span></div></body></html>')


def read(html, asin="B0AAAAAAAA"):
    return s.choose_offer(ap.parse(html, TODAY, asin))


def row(asin="B0AAAAAAAA", policy="CONTINUE", price=6000.0, **kw):
    base = {"productId": "p-" + asin, "handle": "h-" + asin, "vendor": "e.l.f.", "variantId": "v-" + asin, "variant": "Warm",
            "asin": asin, "price": price, "policy": policy, "policy0": policy, "grams": 200, "range": "standard",
            "state": {}, "fallback": "", "blocked": False, "parked": False, "nvariants": 1}
    return {**base, **kw}


def test_reading():
    pg = read(page())
    assert s.sellable(pg) and pg["aed"] == 54.0 and pg["sourceDays"] == 1 and pg["seller"] == "Padimu", pg
    assert pg["availability"] == "In Stock" and pg["location"].startswith("Dubai") and pg["variation"] == "Warm", pg
    # the price of ANOTHER product lower in the page is never read
    assert read(page(offers=[offer(price="", cart=False, avail="Currently unavailable.")]))["aed"] is None
    # an express date does not count; the free standard one does
    pg = read(page(offers=[offer(deliveries=[delivery("Today 5 PM - 9 PM", "fastest", "ARRANGED"),
                                             delivery("Friday, 13 November")])]))
    assert pg["sourceDays"] == 3 and not s.sellable(pg), pg
    # order #1048 (11 Nov evening): free date in 3 days "on your first order" but "Or fastest delivery Tomorrow". The
    # fastest date counts when Amazon ships the offer itself: sold by Amazon.ae, or another seller's stock "Fulfilled by
    # Amazon" (most of the catalogue). Not when the seller ships it, nor "Delivered by Amazon.ae" (seller hands it over).
    both = [delivery("Friday, 13 November", program="ncp"), delivery("Tomorrow, 11 November", "fastest", "DELIVERY")]
    for ships, seller in (("amazon", "Amazon.ae"), ("fba", "Kuwa Supplements")):
        pg = read(page(offers=[offer(seller=seller, ships=ships, deliveries=both)]))
        assert pg["amazonShips"] and pg["sourceDays"] == 1 and s.sellable(pg) and pg["deliveryFee"] == 0.0, pg
        assert pg["promises"] == "free: Friday, 13 November | fastest: Tomorrow, 11 November", pg
    for ships in ("seller", "easyship"):
        pg = read(page(offers=[offer(seller="Padimu", ships=ships, deliveries=both)]))
        assert not pg["amazonShips"] and pg["sourceDays"] == 3 and not s.sellable(pg), pg
    assert not read(page(offers=[offer(seller="Amazon US", ships="seller", deliveries=both)]))["amazonShips"]  # import
    # Rush / same-day stay out, even shipped by Amazon
    pg = read(page(offers=[offer(seller="Amazon.ae", ships="amazon",
                                 deliveries=[delivery("Today 5 PM - 9 PM", "fastest", "ARRANGED"),
                                             delivery("Overnight by 12:09 AM", "Rush", "ARRANGED", "express"),
                                             delivery("Friday, 13 November")])]))
    assert pg["sourceDays"] == 3 and not s.sellable(pg), pg
    # only a paid standard delivery: sellable, and its fee is part of the cost
    pg = read(page(offers=[offer(price="72.00", deliveries=[delivery("Thursday, 12 November", "AED9")])]))
    assert s.sellable(pg) and pg["deliveryFee"] == 9.0 and s.cost_of(pg) == 81.0, pg
    # in stock but no delivery date for Dubai, a pre-order, a tiny stock: not sellable
    assert not s.sellable(read(page(offers=[offer()])))
    assert not s.sellable(read(page(offers=[offer(avail="This item will be released on 2 December 2026. Pre-order now.",
                                                  deliveries=[delivery("Tomorrow, 11 November")])])))
    pg = read(page(offers=[offer(avail="Only 3 left in stock - order soon.", deliveries=[delivery("Tomorrow, 11 November")])]))
    assert pg["stockLeft"] == 3 and not s.sellable(pg), pg
    # two offers: the second one is bought when the first cannot be sold
    pg = read(page(offers=[offer(avail="Only 2 left in stock - order soon.", deliveries=[delivery("Tomorrow, 11 November")]),
                           offer(price="60.50", seller="Amazon.ae", deliveries=[delivery("Thursday, 12 November")])]))
    assert s.sellable(pg) and pg["offer"] == 1 and pg["aed"] == 60.5 and pg["seller"] == "Amazon.ae", pg
    # a seller we never saw, another shade label, another title: still the same ASIN, still sellable (Hoodo, 10 Nov)
    assert s.sellable(read(page(variation="Tan Latte", offers=[offer(seller="Somebody LLC",
                                                                       deliveries=[delivery("Tomorrow, 11 November")])])))


def test_not_the_same_item():
    pg = read(page(shown="B0BBBBBBBB"))  # the page is about another ASIN
    assert pg.get("redirect") == "B0BBBBBBBB" and not s.sellable(pg), pg
    pg = read("<html><head><title>Page Not Found</title></head><body>Sorry</body></html>")
    assert pg.get("gone") and not s.sellable(pg), pg
    # unreadable pages are errors, never "out of stock"
    assert read("<html><body>Enter the characters you see: captcha</body></html>")["error"] == "captcha"
    assert read(page(city="Abu Dhabi"))["error"] == "location"
    assert read(page().replace('id="desktop_buybox"', 'id="x"'))["error"] == "no buy box"


def decide(rows, pages, **kw):
    decisions, info = s.plan(rows, pages, NOW, **kw)
    return {d["r"]["asin"]: d for d in decisions}, info


def test_plan():
    ok = read(page())
    out = read(page(offers=[offer(price="", cart=False, avail="Currently unavailable.")]))
    # back on sale, put to Épuisé, unread page left alone
    d, info = decide([row("B0AAAAAAAA", "DENY"), row("B0AAAAAAAB"), row("B0AAAAAAAC")],
                     {"B0AAAAAAAA": ok, "B0AAAAAAAB": out, "B0AAAAAAAC": {"error": "captcha"}})
    assert d["B0AAAAAAAA"]["policy"] == "CONTINUE" and d["B0AAAAAAAB"]["policy"] == "DENY" and "B0AAAAAAAC" not in d
    assert all(x["applied"] for x in d.values()) and not info["guard"]
    # a hand-blocked variant and a variant cooling down after a failed order are never sold
    future = s.iso(NOW + dt.timedelta(hours=5))
    d, _ = decide([row("B0AAAAAAAA", blocked=True), row("B0AAAAAAAB", "DENY", state={"cool": future}),
                   row("B0AAAAAAAC", "DENY", state={"cool": s.iso(NOW - dt.timedelta(hours=1))})],
                  {a: ok for a in ("B0AAAAAAAA", "B0AAAAAAAB", "B0AAAAAAAC")})
    assert d["B0AAAAAAAA"]["policy"] == "DENY" and d["B0AAAAAAAB"]["policy"] == "DENY"
    assert d["B0AAAAAAAC"]["policy"] == "CONTINUE" and "cool" not in d["B0AAAAAAAC"]["state"]
    # stock guard: too many newly Épuisé at once = nothing written, not even the "verified" stamp
    rows = [row(f"B0AAAAAA{n:02d}") for n in range(30)]
    pages = {r["asin"]: (out if n < 15 else ok) for n, r in enumerate(rows)}
    d, info = decide(rows, pages)
    assert info["guard"] and not any(x["applied"] for x in d.values())
    # ...and the variants hidden during the reading count in the guard
    for r in rows[:15]:
        r["policy"] = "DENY"
    d, info = decide(rows, pages, hidden={r["variantId"] for r in rows[:15]})
    assert info["guard"]
    d, info = decide(rows, pages)
    assert not info["guard"]  # already Épuisé before the run: not "newly" out
    # a hidden product comes back when one variant is sellable
    d, info = decide([row(parked=True, policy="DENY")], {"B0AAAAAAAA": ok})
    assert info["revive"] == {"p-B0AAAAAAAA"} and d["B0AAAAAAAA"]["price"] == s.formula(54.0, 200)


def test_evening():
    """From EVENING_FROM_HOUR to midnight (Dubai) the dates slip by a day: a variant on sale keeps one day of slack, a
    variant that is Épuisé must meet the strict rule to come back (measured 10-11 Nov, order #1048)."""
    def at(hour, when="Friday, 13 November"):  # 3 days from TODAY, offer shipped by the seller (no fastest date)
        return {**read(page(offers=[offer(deliveries=[delivery(when)])])), "hour": hour}
    assert s.days_allowed(True, 21) == 3 and s.days_allowed(True, 10) == 2 and s.days_allowed(False, 21) == 2
    assert s.days_allowed(True, None) == 2 and s.days_allowed(True, s.EVENING_FROM_HOUR) == 3
    d, _ = decide([row("B0AAAAAAAA"), row("B0AAAAAAAB", "DENY"), row("B0AAAAAAAC"), row("B0AAAAAAAD"),
                   row("B0AAAAAAAE", parked=True)],
                  {"B0AAAAAAAA": at(21), "B0AAAAAAAB": at(21), "B0AAAAAAAC": at(10),
                   "B0AAAAAAAD": at(21, "Saturday, 14 November"), "B0AAAAAAAE": at(21)})
    assert d["B0AAAAAAAA"]["policy"] == "CONTINUE"  # on sale, evening, one day late: stays
    assert d["B0AAAAAAAA"]["days"] == s.MAX_DAYS  # ...and the shop label does not move
    assert d["B0AAAAAAAB"]["policy"] == "DENY"  # Épuisé: does not come back on an evening date
    assert d["B0AAAAAAAC"]["policy"] == "DENY"  # morning: the strict rule
    assert d["B0AAAAAAAD"]["policy"] == "DENY"  # two days late: out, even in the evening
    assert d["B0AAAAAAAE"]["policy"] == "DENY"  # a hidden product is never brought back by the slack
    # hidden during this very run (policy already DENY, policy0 still CONTINUE): still counts as on sale
    r = row("B0AAAAAAAA")
    r["policy"] = "DENY"
    assert decide([r], {"B0AAAAAAAA": at(21)})[0]["B0AAAAAAAA"]["policy"] == "CONTINUE"
    # two offers in the evening: the one inside the strict rule is bought, not the cheaper late one
    two = {**read(page(offers=[offer(deliveries=[delivery("Friday, 13 November")]),
                               offer(price="60.50", seller="Amazon.ae", ships="amazon",
                                     deliveries=[delivery("Thursday, 12 November")])])), "hour": 22}
    pg, ok = s.offer_for(two, True)
    assert ok and pg["offer"] == 1 and pg["aed"] == 60.5, pg
    late = {**read(page(offers=[offer(price="", cart=False, avail="Currently unavailable."),
                                offer(price="60.50", deliveries=[delivery("Friday, 13 November")])])), "hour": 22}
    pg, ok = s.offer_for(late, True)
    assert ok and pg["offer"] == 1, pg
    assert not s.offer_for(late, False)[1]


def test_order_check():
    """The order check decides like the stock check, reads twice before saying "ko", and only keeps a variant Épuisé
    for a day when the reason is about stock."""
    item = {"sku": "B0AAAAAAAA", "quantity": 1, "variant": {"fallback": None}}
    slow = {**read(page(offers=[offer(deliveries=[delivery("Friday, 13 November")])])), "hour": 21}  # 3 days, evening
    slower = {**read(page(offers=[offer(deliveries=[delivery("Saturday, 14 November")])])), "hour": 21}
    tiny = {**read(page(offers=[offer(avail="Only 2 left in stock - order soon.",
                                      deliveries=[delivery("Tomorrow, 11 November")])])), "hour": 10}
    good = {**read(page()), "hour": 10}
    calls = []

    def reader(*answers):
        answers = list(answers)

        def page_of(asin, again=False):
            calls.append(again)
            return answers.pop(0) if len(answers) > 1 else answers[0]
        return page_of
    assert oc.check_item(item, reader(slow), {})[0] == "ok"  # evening, one day late: fine (order #1048)
    verdict, why, _, cool = oc.check_item(item, reader(slower), {})
    assert verdict == "ko" and not cool and "trop lente" in why and "Saturday, 14 November" in why, why
    assert calls[-2:] == [False, True]  # read a second time before the verdict
    assert oc.check_item(item, reader(slower, good), {})[0] == "ok"  # the second reading wins
    verdict, why, _, cool = oc.check_item(item, reader(tiny), {})
    assert verdict == "ko" and cool and "2 restant" in why, why  # a stock reason: the variant cools down
    assert oc.check_item(item, reader({"error": "captcha"}), {})[0] == "unknown"
    assert oc.check_item(item, reader(slower, {"error": "captcha"}), {})[0] == "ko"  # second reading failed: first stands


def test_prices():
    ok = read(page())
    fair = s.formula(54.0, 200)
    d, _ = decide([row(price=fair + 400.0)], {"B0AAAAAAAA": ok})  # a normal change is applied
    assert d["B0AAAAAAAA"]["price"] == fair and d["B0AAAAAAAA"]["hold"] is None
    d, _ = decide([row(price=fair * 3.0)], {"B0AAAAAAAA": ok})  # a fall of two thirds is held, the old price stays
    x = d["B0AAAAAAAA"]
    assert x["price"] is None and x["hold"] == "drop" and x["policy"] == "CONTINUE" and x["state"]["pend"]["aed"] == 54.0
    later = NOW + dt.timedelta(hours=4)  # the same amount read again 4 h later: applied
    d = s.plan([row(price=fair * 3.0, state=x["state"])], {"B0AAAAAAAA": ok}, later)[0][0]
    assert d["price"] == fair and "pend" not in d["state"]
    d, _ = decide([row(price=fair / 4.0)], {"B0AAAAAAAA": ok})  # a rise beyond +150 %: held and not sold meanwhile
    assert d["B0AAAAAAAA"]["hold"] == "rise" and d["B0AAAAAAAA"]["policy"] == "DENY"


def test_second_source():
    out = read(page(offers=[offer(price="", cart=False, avail="Currently unavailable.")]))
    mod = suppliers.module_of("PSAE-some-racket")[0]
    good = {"aed": 300.0, "qty": 1, "available": True, "publish": True, "sourceDays": mod.DUBAI_DAYS}
    r = row(policy="DENY", fallback="PSAE-some-racket", price=float(s.formula(300.0, 200)))
    d = s.plan([r], {"B0AAAAAAAA": out}, NOW, fetch_other=lambda m, slug: good)[0][0]
    assert d["policy"] == "CONTINUE" and d["src"] == "PSAE-some-racket" and d["state"]["src"] == "PSAE-some-racket", d
    d = s.plan([r], {"B0AAAAAAAA": out}, NOW, fetch_other=lambda m, slug: {**good, "available": False, "qty": 0})[0][0]
    assert d["policy"] == "DENY" and "src" not in d["state"]
    # Amazon.ae first: when it can sell again, the second source is dropped
    r2 = row(fallback="PSAE-some-racket", state={"src": "PSAE-some-racket", "src_t": s.iso(NOW)})
    d = s.plan([r2], {"B0AAAAAAAA": read(page())}, NOW, fetch_other=lambda m, slug: good)[0][0]
    assert d["src"] == "amazon" and "src" not in d["state"]
    # sold from the second source and that source unreadable right now: nothing is written by this run
    d = s.plan([r2], {"B0AAAAAAAA": out}, NOW, fetch_other=lambda m, slug: {"error": "HTTP 503"})[0][0]
    assert not d["applied"]


def test_audit_sources():
    import inventory_audit as audit
    prod = lambda n=1, **kw: {"isGiftCard": False, "variants": {"nodes": [{}] * n}, **kw}  # noqa: E731
    assert audit.source_of(prod(), {"sku": "B0AAAAAAAA"}) == "amazon"
    assert audit.source_of(prod(), {"sku": "AMZ-B0AAAAAAAA"}) == "amazon"
    assert audit.source_of(prod(ref={"value": "https://www.amazon.ae/dp/B0AAAAAAAA"}), {"sku": ""}) == "amazon"
    assert audit.source_of(prod(2, ref={"value": "https://www.amazon.ae/dp/B0AAAAAAAA"}), {"sku": ""}) is None
    assert audit.source_of(prod(), {"sku": None}) is None
    # MedX and PadelShop.ae variants are read by their own syncs: not "without ASIN" (false alert of 10 Nov, 108 variants)
    assert audit.source_of(prod(), {"sku": "MEDX-some-whey"}) == "other"
    assert audit.source_of(prod(), {"sku": "PSAE-some-racket"}) == "other"
    assert audit.source_of(prod(isGiftCard=True), {"sku": ""}) == "gift"
    assert audit.stale_limit(prod(), {"sku": "MEDX-some-whey"}) == suppliers.module_of("MEDX-x")[0].STALE_HOURS
    assert audit.stale_limit(prod(), {"sku": "B0AAAAAAAA"}) == audit.STALE_HOURS


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("amazon tests OK")
