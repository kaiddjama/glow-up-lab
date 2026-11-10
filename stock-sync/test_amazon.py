#!/usr/bin/env python3
"""Offline tests of the Amazon.ae page reading (amazon_page.py) and of the stock decisions (amazon_sync.plan).
Run: python3 -I test_amazon.py   (no network, no Shopify). The pages are small skeletons carrying the same markers as
the real pages studied on 10 Nov (ids of the buy box, delivery tags, identity markers)."""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.pop("PRICE_FORMULA", None)
import amazon_page as ap  # noqa: E402
import amazon_sync as s  # noqa: E402
import suppliers  # noqa: E402

TODAY = dt.date(2026, 11, 10)
NOW = dt.datetime(2026, 11, 10, 9, 0, tzinfo=dt.timezone.utc)
s.MARGIN_CUSTOMS, s.SHIPPING_AED_PER_KG, s.AED_TO_FDJ = 2.0, 10.0, 50.0  # test values, not the real formula


def delivery(when, price="FREE", mir="", program=""):
    return (f'<span data-csa-c-type="element" data-csa-c-delivery-price="{price}" data-csa-c-mir-type="{mir}" '
            f'data-csa-c-delivery-benefit-program-id="{program}" data-csa-c-delivery-time="{when}">x</span>')


def offer(price="54.00", avail="In Stock", deliveries=(), seller="Padimu", cart=True, qty=10):
    whole, frac = (price.split(".") + ["00"])[:2] if price else ("", "")
    return "".join([
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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("amazon tests OK")
