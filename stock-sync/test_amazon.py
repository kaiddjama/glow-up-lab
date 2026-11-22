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


# the Amazon Now buy box as on the real pages of 11 Nov (delivery in minutes, its own basket)
NOW_OFFER = ('<div id="desktop_almBuyBox"><div id="almDesktopSingleOfferPriceWrapper"><div id="corePrice_feature_div">'
             '<span class="a-price"><span class="a-offscreen">AED&nbsp;29.35</span></span></div></div><div '
             'id="almLogoAndDeliveryMessage">FREE 15\u201325 mins delivery on orders over AED15 with Prime</div><div '
             'id="almAvailability_feature_div"><span id="availability-string"> In Stock </span></div><div '
             'id="almAddToCart_feature_div"><input name="submit.alm-add-to-cart" type="submit"></div>Dispatched from '
             "AmazonNow Sold by AmazonNow</div>")


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


def test_page_changes():
    """Amazon.ae changes its pages. Every fact has a spare reading that gives the same answer; an offer that cannot be
    understood counts as NOT READ, never as out of stock; one reader raises the alert when it happens on many pages."""
    form = '<input type="hidden" name="items[0.base][customerVisiblePrice][amount]" value="54.0">'
    words = ("<div>FREE delivery <b>Friday, 13 November</b> on your first order. Or fastest delivery <b>Tomorrow, "
             "11 November</b>. Order within 2 hrs 10 mins</div>")
    both = [delivery("Friday, 13 November", program="ncp"), delivery("Tomorrow, 11 November", "fastest", "DELIVERY")]
    normal = page(offers=[offer(seller="Kuwa", ships="fba", deliveries=both) + form + words])
    ref = read(normal)
    assert ref["via"] == ref["blind"] == ref["pageVia"] == ref["pageBlind"] == [] and ref["sourceDays"] == 1, ref
    facts = ("aed", "inStock", "stockLeft", "sourceDays", "amazonShips", "deliveryFee", "seller")
    changes = {"price": ('id="corePrice_feature_div"', 'id="newPrice"'), "delivery": ("data-csa-c-delivery-", "data-new-"),
               "stock": ('id="availability"', 'id="newAvailability"'), "cart": ('id="add-to-cart-button"', 'id="buy-now-button"'),
               "shipper": ("InfoFeature_feature_div", "Info_new_div")}
    everything = normal
    for fact, (old, new) in changes.items():
        pg = read(normal.replace(old, new))
        assert [pg[k] for k in facts] == [ref[k] for k in facts] and pg["via"] == [fact] and s.sellable(pg), (fact, pg)
        everything = everything.replace(old, new)
    pg = read(everything.replace('id="productTitle"', 'id="title"').replace('id="desktop_buybox"', 'id="buybox"'))
    assert [pg[k] for k in facts] == [ref[k] for k in facts] and sorted(pg["via"]) == sorted(changes), pg
    assert pg["pageVia"] == ["title", "buybox"] and pg["title"] == "e.l.f. Camo Concealer", pg
    # the low stock line is still seen through the spare reading
    low = normal.replace("In Stock", "Only 2 left in stock - order soon.").replace('id="availability"', 'id="newAvailability"')
    assert read(low)["stockLeft"] == 2 and not s.sellable(read(low))
    # spare delivery reading: a time slot is express and never counts; a seller-shipped offer keeps the free date
    slot = words.replace("Tomorrow, 11 November", "Today 5 PM - 9 PM")
    pg = read(page(offers=[offer(seller="Kuwa", ships="fba") + form + slot]))
    assert pg["sourceDays"] == 3 and pg["via"] == ["delivery"] and not s.sellable(pg), pg
    assert read(page(offers=[offer(ships="seller") + words]))["sourceDays"] == 3
    # an offer nobody understands: NOT READ (error), whatever is missing; a page that SAYS unavailable is read as such
    bare = page(offers=[offer(deliveries=both)])
    assert read(bare.replace('id="corePrice_feature_div"', 'id="x"'))["error"] == "layout: price"
    assert read(bare.replace('id="add-to-cart-button"', 'id="x"'))["error"] == "layout: cart"
    assert read(page(offers=[offer(price="", cart=False, avail="")]))["error"] == "layout: offer"
    gone = read(page(offers=[offer(price="", cart=False, avail="Currently unavailable.")]))
    assert not gone.get("error") and not gone["inStock"] and s.why_out(gone) == "rupture", gone
    # the "Currently unavailable" box has its own stock line: a normal reading, not a spare one
    box = ('<div id="outOfStock" class="a-box"><span class="a-color-price a-text-bold">Currently unavailable.</span><br>We '
           "don't know when or if this item will be back in stock.</div>")
    pg = read(page(offers=[box]))
    assert not pg["inStock"] and pg["via"] == [] and pg["availability"] == "Currently unavailable.", pg
    # Amazon Now featured (delivery in minutes, its own basket, no ordinary "Add to cart"): recognised by its own box,
    # neither "not read" nor a plain out of stock; not sold, and the reason says so
    pg = read(page(offers=[NOW_OFFER]))
    assert not pg.get("error") and pg["amazonNow"] and not pg["inStock"] and pg["aed"] == 29.35 and pg["via"] == [], pg
    assert pg["availability"] == "In Stock" and not s.sellable(pg) and s.why_out(pg) == "amazon-now", pg
    assert s.layout_watch({"B0": pg, "B1": ref})[0]["amazonNow"] == 1
    assert not read(normal)["amazonNow"] and s.why_out(gone) == "rupture"
    # an ordinary offer shown next to an Amazon Now box is read as usual
    pg = read(page(offers=[offer(seller="Kuwa", ships="fba", deliveries=both) + NOW_OFFER]))
    assert pg["inStock"] and not pg["amazonNow"] and s.sellable(pg), pg
    unread = {"B0AAAAAAAA": read(bare.replace('id="corePrice_feature_div"', 'id="x"'))}
    decisions, _ = decide([row()], unread)
    assert not decisions, decisions  # a page not read changes nothing: not hidden, not confirmed
    # facts found by no reading on an offer that can be bought: reported, the offer is still read
    pg = read(page(city="", offers=[offer(avail="", deliveries=both)]))
    assert pg["blind"] == ["stock"] and pg["pageBlind"] == ["location"] and s.sellable(pg, 3), pg
    # one reader: a few odd pages are just read again; many raise the alert, by fact
    ok, odd, spare = read(normal), read(bare.replace('id="corePrice_feature_div"', 'id="x"')), read(normal.replace(*changes["price"]))
    stats, alerts = s.layout_watch({**{f"A{k}": ok for k in range(26)}, **{f"B{k}": odd for k in range(4)}})
    assert stats["unreadable"] == {"price": 4} and not alerts, (stats, alerts)
    stats, alerts = s.layout_watch({**{f"A{k}": ok for k in range(22)}, **{f"B{k}": odd for k in range(8)}})
    assert len(alerts) == 1 and "the price (8)" in alerts[0], alerts
    stats, alerts = s.layout_watch({**{f"A{k}": ok for k in range(18)}, **{f"B{k}": spare for k in range(12)}})
    assert stats["spare"] == {"price": 12} and len(alerts) == 1 and "spare reading" in alerts[0], (stats, alerts)
    # far more "in stock without a date" pages than Amazon.ae ever has: a changed delivery block, those pages are not read
    nodate = read(page(offers=[offer()]))
    few = {**{f"A{k}": ok for k in range(28)}, **{f"B{k}": dict(nodate) for k in range(2)}}
    assert s.layout_watch(few)[1] == [] and not few["B0"].get("error")
    many = {**{f"A{k}": ok for k in range(20)}, **{f"B{k}": dict(nodate) for k in range(10)}}
    stats, alerts = s.layout_watch(many)
    assert stats["noDateInBulk"] == 10 and many["B0"]["error"] == "layout: delivery" and len(alerts) == 1, (stats, alerts)


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
    d, info = decide([row(parked=True, policy="DENY", price=5000.0)], {"B0AAAAAAAA": ok})
    assert info["revive"] == {"p-B0AAAAAAAA"} and d["B0AAAAAAAA"]["price"] == s.formula(54.0, 200)
    # ...at its old price when Amazon.ae is cheaper than before: a fall waits, for a product that comes back too
    d, info = decide([row(parked=True, policy="DENY")], {"B0AAAAAAAA": ok})
    assert info["revive"] == {"p-B0AAAAAAAA"} and d["B0AAAAAAAA"]["price"] is None and d["B0AAAAAAAA"]["hold"] == "wait"


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


def test_low_stock_and_reasons():
    """A stock moving around the threshold no longer puts a variant on sale and off at every check, and every Épuisé
    variant carries the reason (130 variants changed state twice or more in 24 h on 10-11 Nov)."""
    def left(n):
        return read(page(offers=[offer(avail=f"Only {n} left in stock - order soon.",
                                       deliveries=[delivery("Tomorrow, 11 November")])]))
    d, _ = decide([row("B0AAAAAAAA"), row("B0AAAAAAAB"), row("B0AAAAAAAC", "DENY"), row("B0AAAAAAAD", "DENY"),
                   row("B0AAAAAAAE", "DENY")],
                  {"B0AAAAAAAA": left(3), "B0AAAAAAAB": left(4), "B0AAAAAAAC": left(5), "B0AAAAAAAD": left(6),
                   "B0AAAAAAAE": read(page())})
    assert d["B0AAAAAAAA"]["policy"] == "DENY" and d["B0AAAAAAAA"]["state"]["why"] == "stock-bas"
    assert d["B0AAAAAAAB"]["policy"] == "CONTINUE" and "why" not in d["B0AAAAAAAB"]["state"]  # on sale with 4: stays
    assert d["B0AAAAAAAC"]["policy"] == "DENY" and d["B0AAAAAAAC"]["why"] == "stock-bas"  # Épuisé with 5: not back yet
    assert d["B0AAAAAAAD"]["policy"] == "CONTINUE"  # more than LOW_STOCK_BACK: back
    assert d["B0AAAAAAAE"]["policy"] == "CONTINUE"  # plain "In Stock": back
    out = read(page(offers=[offer(price="", cart=False, avail="Currently unavailable.")]))
    late = read(page(offers=[offer(deliveries=[delivery("Friday, 13 November")])]))
    far = read(page(offers=[offer(deliveries=[delivery("17 - 19 November")])]))
    future = s.iso(NOW + dt.timedelta(hours=5))
    d, _ = decide([row("B0AAAAAAAA"), row("B0AAAAAAAB"), row("B0AAAAAAAC"), row("B0AAAAAAAD"), row("B0AAAAAAAE", blocked=True),
                   row("B0AAAAAAAF", "DENY", state={"cool": future}), row("B0AAAAAAAG"), row("B0AAAAAAAH"),
                   row("B0AAAAAAAI", state={"why": "rupture"})],
                  {"B0AAAAAAAA": out, "B0AAAAAAAB": late, "B0AAAAAAAC": far, "B0AAAAAAAD": read(page(offers=[offer()])),
                   "B0AAAAAAAE": read(page()), "B0AAAAAAAF": read(page()), "B0AAAAAAAG": read(page(shown="B0BBBBBBBB")),
                   "B0AAAAAAAH": read("<html><head><title>Page Not Found</title></head><body>Sorry</body></html>"),
                   "B0AAAAAAAI": read(page())})
    assert [d[f"B0AAAAAAA{x}"]["why"] for x in "ABCDEFGH"] == [
        "rupture", "delai:3", "delai:4+", "sans-date", "retenue", "pause-commande", "autre-article", "fiche-supprimee"]
    assert d["B0AAAAAAAI"]["policy"] == "CONTINUE" and "why" not in d["B0AAAAAAAI"]["state"]  # back on sale: reason dropped


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
    verdict, why, _, cool = oc.check_item(item, reader({**read(page(offers=[NOW_OFFER])), "hour": 10}), {})
    assert verdict == "ko" and cool and "Amazon Now" in why, why  # no ordinary offer: the owner is told what is shown
    assert oc.check_item(item, reader({"error": "captcha"}), {})[0] == "unknown"
    assert oc.check_item(item, reader(slower, {"error": "captcha"}), {})[0] == "ko"  # second reading failed: first stands


def test_reader_keeps_its_address():
    """One odd header must not stop a whole reader: the buy box line counts, then the address is set again once; the
    reader stops only when the city still does not show (a reader stopped after 24 of 163 pages on 11 Nov)."""
    import browser_fetch as bf

    class Page:
        def __init__(self, header, buybox, after_reset=None):
            self.header, self.buybox, self.after_reset, self.loads = header, buybox, after_reset, 0

        def goto(self, url, wait_until=None):
            self.loads += 1

        def wait_for_selector(self, *a, **k): pass
        def wait_for_timeout(self, ms): pass
        def content(self): return "<html>page</html>"
        def locator(self, sel): return type("L", (), {"count": lambda self: 0})()

        def inner_text(self, sel, timeout=None):
            if sel == bf.LOCATION_TEXT:
                return self.header
            if self.buybox is None:
                raise RuntimeError("no buy box line")
            return self.buybox

    def reader(page):
        r = bf.BrowserReader()
        r.page, r.count, r.resets = page, bf.CHECK_EVERY - 1, 0

        def again():
            r.resets += 1
            if page.after_reset is None:
                raise bf.LocationLost("delivery location is 'Update location', not Dubai")
            page.header = page.after_reset
        r.set_location = again
        return r

    url = "https://www.amazon.ae/dp/B0AAAAAAAA"
    r = reader(Page("Dubai, Ras ...", "Deliver to Dubai, Ras Al Khor"))  # the normal page
    assert r.get(url) and r.resets == 0 and r.page.loads == 1
    r = reader(Page("Update location", "Deliver to Dubai, Ras Al Khor"))  # odd header, the buy box still says Dubai
    assert r.get(url) and r.resets == 0 and r.page.loads == 1
    r = reader(Page("Update location", None, after_reset="Dubai, Ras ..."))  # address lost, set again, page read again
    assert r.get(url) and r.resets == 1 and r.page.loads == 2
    for page in (Page("Abu Dhabi", "Deliver to Abu Dhabi", after_reset="Abu Dhabi"), Page("Update location", None)):
        r = reader(page)  # the city cannot be put back: the reader stops, nothing is read for another address
        try:
            r.get(url)
            raise AssertionError("the reader went on with another address")
        except bf.LocationLost:
            pass


def test_token_tries_again():
    """Shopify answering 502 for a moment must not fail a whole job (false alert of 22 Nov); a refusal fails at once."""
    import io
    import json
    import urllib.error
    keep = {k: os.environ.get(k) for k in ("SHOPIFY_TOKEN", "SHOPIFY_STORE", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET")}
    real_open, real_sleep = s.urllib.request.urlopen, s.time.sleep
    waits = []

    def http(code):
        return urllib.error.HTTPError("https://x", code, "x", {}, io.BytesIO(b""))

    class Reply(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def opener(answers):
        answers = list(answers)

        def urlopen(req, timeout=None):
            a = answers.pop(0)
            if isinstance(a, Exception):
                raise a
            return Reply(json.dumps(a).encode())
        return urlopen
    try:
        os.environ.update({"SHOPIFY_STORE": "x.myshopify.com", "SHOPIFY_CLIENT_ID": "id", "SHOPIFY_CLIENT_SECRET": "secret"})
        s.time.sleep = waits.append
        os.environ.pop("SHOPIFY_TOKEN", None)
        s.urllib.request.urlopen = opener([http(502), TimeoutError(), http(503), {"access_token": "tok"}])
        assert s.token() == "tok" and len(waits) == 3, waits
        os.environ.pop("SHOPIFY_TOKEN", None)
        s.urllib.request.urlopen = opener([http(401), {"access_token": "never"}])
        try:
            s.token()
            raise AssertionError("a refused request was tried again")
        except urllib.error.HTTPError as e:
            assert e.code == 401 and len(waits) == 3
        s.urllib.request.urlopen = opener([http(502)] * 6)
        try:
            s.token()
            raise AssertionError("no token and no error")
        except urllib.error.HTTPError as e:
            assert e.code == 502 and len(waits) == 8, waits  # 6 tries, then the real alert
    finally:
        s.urllib.request.urlopen, s.time.sleep = real_open, real_sleep
        for k, v in keep.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_prices():
    ok = read(page())
    fair = s.formula(54.0, 200)
    d, _ = decide([row(price=fair - 400.0)], {"B0AAAAAAAA": ok})  # a rise is applied at once
    assert d["B0AAAAAAAA"]["price"] == fair and d["B0AAAAAAAA"]["hold"] is None
    d, _ = decide([row(price=fair / 4.0)], {"B0AAAAAAAA": ok})  # a rise beyond +150 %: held and not sold meanwhile
    assert d["B0AAAAAAAA"]["hold"] == "rise" and d["B0AAAAAAAA"]["policy"] == "DENY"
    held = d["B0AAAAAAAA"]["state"]
    d = s.plan([row(price=fair / 4.0, state=held)], {"B0AAAAAAAA": ok}, NOW + dt.timedelta(hours=4))[0][0]
    assert d["price"] == fair and d["policy"] == "CONTINUE" and "pend" not in d["state"]  # read again 4 h later: applied

    # Since 15 Nov: a fall is not followed at once (orders #1048, #1050, #1055, #1061: NYX prices low for a few hours).
    def at(hours, shop, state, aed="54.00"):
        pg = read(page(offers=[offer(price=aed, deliveries=[delivery("Tomorrow, 11 November")])]))
        return s.plan([row(price=float(shop), state=state)], {"B0AAAAAAAA": pg}, NOW + dt.timedelta(hours=hours))[0][0]
    shop = fair + 400
    x = at(0, shop, {})  # Amazon.ae is cheaper than the shop price: nothing changes, the variant stays on sale
    assert x["price"] is None and x["hold"] == "wait" and x["policy"] == "CONTINUE" and x["state"]["low"]["n"] == 1
    x = at(5, shop, x["state"], "50.00")  # still cheaper (and cheaper still): the highest reading is remembered
    assert x["price"] is None and x["state"]["low"] == {"t": s.iso(NOW), "fdj": fair, "n": 2}
    x = at(47, shop, at(30, shop, x["state"])["state"])  # four readings but not two days yet
    assert x["price"] is None and x["hold"] == "wait" and x["state"]["low"]["n"] == 4
    y = at(49, shop, x["state"], "50.00")  # two days below the shop price: down to the HIGHEST of those readings
    assert y["price"] == fair and y["hold"] is None and "low" not in y["state"]
    few = at(49, shop, {"low": {"t": s.iso(NOW), "fdj": fair, "n": 1}})  # two days, but only two readings: not enough
    assert few["price"] is None and few["state"]["low"]["n"] == 2
    back = at(20, fair, {"low": {"t": s.iso(NOW), "fdj": fair - 500, "n": 3}})  # back at the shop price: forgotten
    assert back["price"] is None and back["hold"] is None and "low" not in back["state"]
    up = at(20, fair - 500, {"low": {"t": s.iso(NOW), "fdj": fair - 900, "n": 3}})  # a rise meanwhile: applied, forgotten
    assert up["price"] == fair and "low" not in up["state"]
    # the NYX blush of 12-13 Nov: 21.67 AED, 39 the next morning, 21.67 at noon, 38 in the afternoon. The shop stays at 39.
    high, state, prices = s.formula(39.0, 200), {}, []
    for hours, aed in ((0, "21.67"), (16, "39.00"), (23, "21.67"), (26, "38.00"), (35, "39.00"), (60, "21.67")):
        x = at(hours, high, state, aed)
        state, prices = x["state"], prices + [x["price"]]
        assert x["policy"] == "CONTINUE"
    assert prices == [None] * 6 and state["low"]["n"] == 1  # never sold below the price it costs most of the time
    hand = at(0, fair - 50, {"low": {"t": s.iso(NOW - dt.timedelta(hours=60)), "fdj": fair + 200, "n": 9}}, "50.00")
    assert hand["price"] is None and hand["state"]["low"]["n"] == 1  # shop price lowered by hand meanwhile: starts again

    # PRICE_DROP_HOURS=0 gives the rule of 10 Nov back: falls applied at once, beyond 40 % after a second reading
    s.PRICE_DROP_HOURS = 0
    try:
        d, _ = decide([row(price=fair + 400.0)], {"B0AAAAAAAA": ok})
        assert d["B0AAAAAAAA"]["price"] == fair and d["B0AAAAAAAA"]["hold"] is None
        d, _ = decide([row(price=fair * 3.0)], {"B0AAAAAAAA": ok})  # a fall of two thirds is held, the old price stays
        x = d["B0AAAAAAAA"]
        assert x["price"] is None and x["hold"] == "drop" and x["policy"] == "CONTINUE" and x["state"]["pend"]["aed"] == 54.0
        d = s.plan([row(price=fair * 3.0, state=x["state"])], {"B0AAAAAAAA": ok}, NOW + dt.timedelta(hours=4))[0][0]
        assert d["price"] == fair and "pend" not in d["state"]
    finally:
        s.PRICE_DROP_HOURS = 48.0


def test_order_price():
    """Since 15 Nov the order check compares the price the customer paid with what Amazon.ae asks when the order arrives."""
    def item(paid, qty=1, grams=200):
        return {"sku": "B0AAAAAAAA", "quantity": qty, "originalUnitPriceSet": {"shopMoney": {"amount": str(paid)}},
                "variant": {"fallback": None, "product": {"weight": {"value": str(grams)}, "tags": []}}}
    good = {**read(page()), "hour": 10}  # 54 AED today
    fair, costs = s.formula(54.0, 200), []
    verdict, _, notes, _ = oc.check_item(item(float(fair)), lambda a, again=False: good, {}, costs)
    assert verdict == "ok" and notes == [] and costs == [{"sku": "B0AAAAAAAA", "asin": "B0AAAAAAAA", "qty": 1,
                                                            "paid": float(fair), "aed": 54.0}]
    assert oc.check_item(item(fair + 2000.0), lambda a, again=False: good, {})[2] == []  # Amazon.ae cheaper: nothing to say
    assert oc.check_item(item(fair - 100.0), lambda a, again=False: good, {})[2] == []  # a small gap (under 5 %): nothing
    low = s.formula(21.67, 200)  # paid on a price of 21.67 AED, Amazon.ae at 54 AED when the order arrives
    verdict, _, notes, _ = oc.check_item(item(float(low), qty=2), lambda a, again=False: good, {})
    assert verdict == "ok" and [t for t, _ in notes] == ["amazon-prix"], notes
    assert "54.00 AED" in notes[0][1] and "22.00 AED" in notes[0][1] and "3200 Fdj" in notes[0][1], notes
    broken = {**item(float(low)), "originalUnitPriceSet": None}  # no price on the line: no comparison, the order is fine
    assert oc.check_item(broken, lambda a, again=False: good, {})[::2] == ("ok", [])


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
    # why variants are Épuisé and products hidden, counted from the reason kept on each variant
    def var(why=None, policy="DENY", sku="B0AAAAAAAA"):
        return {"sku": sku, "inventoryPolicy": policy, "st": {"value": '{"why":"%s"}' % why} if why else None}
    table = "\n".join(audit.reasons_table([
        {"status": "DRAFT", "tags": ["epuise-auto"], "isGiftCard": False,
         "variants": {"nodes": [var("rupture"), var("rupture"), var("stock-bas")]}},
        {"status": "ACTIVE", "tags": [], "isGiftCard": False,
         "variants": {"nodes": [var("delai:4+"), var(policy="CONTINUE"), var(sku="MEDX-x"), var(), var(sku="")]}}]))
    assert "| En rupture sur Amazon.ae | 2 | 1 |" in table and "| Stock presque fini sur Amazon.ae | 1 | 0 |" in table, table
    assert "| Livraison à Dubaï en 4 jours ou plus | 1 | 0 |" in table and "| Total | 6 | 1 |" in table, table
    assert "| Variante sans ASIN | 1 | 0 |" in table and "Motif pas encore noté" in table, table


def test_extended_days():
    """A product tagged delai-etendu (makeup best-sellers, 15 Nov) is sold up to EXT_MAX_DAYS days to Dubai and shows the
    long delay; the other products keep the strict MAX_DAYS."""
    four = read(page(offers=[offer(deliveries=[delivery("Saturday, 14 November")])]))
    five = read(page(offers=[offer(deliveries=[delivery("Sunday, 15 November")])]))
    assert four["sourceDays"] == 4 and five["sourceDays"] == 5
    d, _ = decide([row("B0AAAAAAAA"), row("B0AAAAAAAB", ext=True), row("B0AAAAAAAC", "DENY", ext=True),
                   row("B0AAAAAAAD", ext=True)],
                  {"B0AAAAAAAA": four, "B0AAAAAAAB": four, "B0AAAAAAAC": four, "B0AAAAAAAD": five})
    assert d["B0AAAAAAAA"]["policy"] == "DENY"  # no tag: strict rule
    assert d["B0AAAAAAAB"]["policy"] == "CONTINUE" and d["B0AAAAAAAB"]["days"] == 4  # tagged: sold, true delay kept
    assert d["B0AAAAAAAC"]["policy"] == "CONTINUE"  # tagged and Épuisé: comes back inside the extended rule
    assert d["B0AAAAAAAD"]["policy"] == "DENY"  # five days: out even when tagged
    assert not s.offer_for(four, True)[1] and s.offer_for(four, True, True)[1]
    assert 4 > s.STANDARD_DAYS  # a tagged variant at 4 days is labelled "3-10" (delivery_range)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("amazon tests OK")
