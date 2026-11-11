#!/usr/bin/env python3
"""Reads the HTML of an Amazon.ae product page into the facts the stock sync needs. Pure functions: no network, no Shopify,
so everything here is tested offline against pages saved from the real site (test_amazon.py).

What the page tells us (measured on 23 real pages, 10 Nov 2026, guest session with a Dubai address):
  - which item it is: <link rel="canonical">, <input id="ASIN"> and "currentAsin" all carry the ASIN the page is really about
    (a page that shows another ASIN than the one asked for is a redirection to another item: another shade, another size);
  - the buy box lists one OFFER (price, stock line, delivery promise, add-to-cart button) or several: the featured one
    (id="newAccordionRow_0") and "another way to buy" (newAccordionRow_1...). The old reader only looked at the first 30,000
    characters, so it saw the featured offer's header and nothing else;
  - the delivery promises are tags data-csa-c-delivery-time / -price / -type: FREE standard delivery, a paid standard delivery
    (e.g. AED 9), the plain "Or fastest delivery" line (counted only for an offer that Amazon ships itself, since 11 Nov) and
    express options ("Rush", same day: never counted, they cost extra and are not a promise for every order);
  - who ships: the offer says "Fulfilled by Amazon" (another seller's stock held in Amazon's warehouse) or "Shipper / Seller
    Amazon.ae". "Delivered by Amazon.ae" (the seller hands the parcel over later) and "Amazon US / UK" (import) are not that;
  - a removed listing answers "Page Not Found" (no product title).
Hoodo's rule of 10 Nov: the seller, the wording of the title or of the specs never decide anything. Only the ASIN decides
whether the page is the same item.
"""
import datetime as dt
import html as htmllib
import os
import re

ASIN_RE = re.compile(r"\b(?:AMZ-)?(B0[A-Z0-9]{8})\b")
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}
EXTRA_DAYS = 2  # days after the Dubai delivery date for the date shown in the shop (reception + hand-over)
CITY = os.environ.get("BROWSER_CITY", "Dubai")  # the delivery city the pages must show (browser_fetch.py sets it)
SEGMENT_MAX = 90000  # characters read after the start of one offer (the add-to-cart button is ~60,000 after its row)
ROW_RE = re.compile(r'\sid="(\w*AccordionRow\w*)"')
NEW_ROW_RE = re.compile(r'\sid="newAccordionRow_(\d+)"')
DELIVERY_TAG_RE = re.compile(r"<[^>]*data-csa-c-delivery-time=[^>]*>")


def clean(fragment):
    """Text of an HTML fragment: tags removed, entities decoded, spaces folded."""
    text = re.sub(r"<(script|style)\b.*?(?:</\1>|$)", " ", fragment or "", flags=re.S | re.I)  # inline JSON / CSS is not text
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def dubai_now():
    """Amazon.ae lives on Dubai time (UTC+4)."""
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=4)))


def dubai_today():
    """Amazon.ae dates are Dubai dates; read per page, because a long run can cross midnight."""
    return dubai_now().date()


def days_until(text, today):
    t = text.lower()
    if t.startswith("today") or re.search(r"\b\d+\s*(hr|hrs|hour|hours|min|mins|minutes)\b", t):
        return 0  # same day, including Amazon's "in 1 hr 30 mins" express delivery
    found = re.findall(r"(\d{1,2})\s+([a-z]+)", t)
    if not found and "tomorrow" in t:
        return 1
    if not found:
        return None
    day, month = found[-1]  # a range "19 - 21 November": the last day counts
    month = next((full for full in MONTHS if len(month) >= 3 and full.startswith(month[:3])), None)  # "Oct" or "October"
    if not month:
        return None
    try:
        d = dt.date(today.year, MONTHS[month], int(day))
    except ValueError:
        return None
    if d < today:
        d = dt.date(today.year + 1, MONTHS[month], int(day))
    return (d - today).days


def parse_price(block, via=None):
    """AED price of the buy box (or of one offer) inside this HTML fragment, or None. Never reads another product's price:
    only the price blocks of the fragment itself. via (a list) receives "price" when the spare reading was needed."""
    i = block.find("apex-pricetopay-value")  # the price to pay; its a-offscreen text is often empty
    if i >= 0:
        w = re.search(r'a-price-whole">([\d,]+)', block[i:i + 600])
        f = re.search(r'a-price-fraction">(\d+)', block[i:i + 800])
        if w:
            return float(w.group(1).replace(",", "") + "." + (f.group(1) if f else "0"))
    for anchor in ('id="corePriceDisplay_desktop_feature_div"', 'id="corePrice_feature_div"',
                   'id="corePrice_desktop"', 'id="apex_desktop"'):
        i = block.find(anchor)
        if i < 0:
            continue
        part = block[i:i + 6000]
        m = re.search(r'a-offscreen">\s*(?:AED|د\.إ\.?)\s*&nbsp;?\s*([\d,]+\.?\d*)', part) or \
            re.search(r'a-offscreen">[^<\d]*([\d,]+\.\d{2})', part)
        if m:
            return float(m.group(1).replace(",", ""))
        w = re.search(r'a-price-whole">([\d,]+)', part)
        if w:
            f = re.search(r'a-price-fraction">(\d+)', part[w.end():w.end() + 200])
            return float(w.group(1).replace(",", "") + "." + (f.group(1) if f else "0"))
    # Spare reading, for the day Amazon renames its price blocks: the amount the add-to-cart form of this offer sends (a
    # hidden field). On 65 real offers (11 Nov) it is the displayed price every time. No looser reading than that: a price
    # taken from "the first AED amount around" could be a delivery fee or a crossed-out price.
    m = re.search(r'customerVisiblePrice\]\[amount\]"[^>]*\bvalue="(\d+(?:\.\d+)?)"', block) or \
        re.search(r'\bvalue="(\d+(?:\.\d+)?)"[^>]*customerVisiblePrice\]\[amount\]', block)
    if m and float(m.group(1)) > 0:
        if via is not None:
            via.append("price")
        return float(m.group(1))
    return None


def _attr(tag, name):
    m = re.search(rf'data-csa-c-{name}="([^"]*)"', tag)
    return htmllib.unescape(m.group(1)).strip() if m else ""


def delivery_options(block):
    """The delivery promises of a fragment: [{"text", "kind": free | paid | express, "fee"}].
    free = FREE standard delivery (also "on your first order": a guest always sees it), paid = a standard delivery with a fee
    (AED 9...), fastest = the plain "Or fastest delivery <date>" line (counted only when Amazon ships the offer itself),
    express = "Rush" / same-day arrangements: never counted, they cost extra and are not offered on every order."""
    out = []
    for tag in DELIVERY_TAG_RE.findall(block):
        when = _attr(tag, "delivery-time")
        if not when:
            continue
        price = _attr(tag, "delivery-price").lower()
        mir = _attr(tag, "mir-type").lower()
        program = _attr(tag, "delivery-benefit-program-id").lower()
        if mir == "arranged" or price == "rush" or program == "express" or program.startswith("sub_same_day"):
            out.append({"text": when, "kind": "express", "fee": 0.0})
        elif price == "fastest":
            out.append({"text": when, "kind": "fastest", "fee": 0.0})
        elif price in ("", "free"):
            out.append({"text": when, "kind": "free", "fee": 0.0})
        else:
            m = re.search(r"(\d[\d,]*(?:\.\d+)?)", price)
            out.append({"text": when, "kind": "paid", "fee": float(m.group(1).replace(",", "")) if m else 0.0})
    return out


DATE_TEXT = (r"(?:(?:today|tomorrow|overnight|[a-z]+day),?\s*)?(?:\d{1,2}(?:\s+[a-z]{3,9})?\s*-\s*)?\d{1,2}\s+[a-z]{3,9}"
             r"|today(?:\s+\d{1,2}\s*[ap]m\s*-\s*\d{1,2}\s*[ap]m)?|tomorrow|overnight")
DELIVERY_TEXT_RE = re.compile(r"(FREE delivery|AED\s*[\d.,]+\s+delivery|fastest delivery)\s+(" + DATE_TEXT + r")"
                              r"(\s+\d{1,2}\s*[ap]m\b)?", re.I)


def delivery_options_text(block):
    """Spare reading of the delivery promises, from the words of the offer ("FREE delivery Saturday, 14 November on your
    first order Or fastest delivery Tomorrow, 12 November"), for the day Amazon drops the data-csa-c-delivery-* attributes
    delivery_options reads. Same kinds; a "fastest" promise worded as a time slot ("Today 6 PM - 10 PM") or "Overnight" is
    express (the attributes that told Rush from standard are gone with the rest)."""
    out = []
    for label, when, slot in DELIVERY_TEXT_RE.findall(clean(block)):
        low = label.lower()
        if low.startswith("fastest"):
            rush = slot or re.search(r"overnight|\b[ap]m\b", when, re.I)
            out.append({"text": when, "kind": "express" if rush else "fastest", "fee": 0.0})
        elif low.startswith("free"):
            out.append({"text": when, "kind": "free", "fee": 0.0})
        else:
            m = re.search(r"(\d[\d,]*(?:\.\d+)?)", label)
            out.append({"text": when, "kind": "paid", "fee": float(m.group(1).replace(",", "")) if m else 0.0})
    return out


def pick_delivery(options, today, amazon=False):
    """(days to Dubai, text, delivery fee) of the delivery that counts: the earliest FREE one; only when there is none,
    the earliest paid standard one (its fee is returned so the price can cover it). Express options never count.
    amazon=True (the offer is shipped by Amazon itself, see shipped_by_amazon): the plain "Or fastest delivery" date counts
    too. A guest only gets "FREE delivery <date> on your first order", a slow date that slips by one more day every evening
    (measured 10-11 Nov: 1 day at 19:00 Dubai, 2 days at 21:45; on 11 Nov 2 days all day and 3 days from about 21:00, for
    1,700 of 2,000 variants), while Hoodo's account gets the fastest date: order #1048, 6 NYX items read "Saturday 14",
    she saw "today or tomorrow" and the page said "Or fastest delivery Tomorrow". Offers shipped by the seller keep the
    free date only."""
    free = [o for o in options if o["kind"] == "free" or (amazon and o["kind"] == "fastest")]
    pool = free or [o for o in options if o["kind"] == "paid"]
    scored = [(days_until(o["text"], today), o) for o in pool]
    scored = [x for x in scored if x[0] is not None]
    if not scored:
        return None, (pool[0]["text"] if pool else None), 0.0
    days, o = min(scored, key=lambda x: x[0])
    return days, o["text"], o["fee"]


def _feature(block, name):
    """(label, value) of one line of the "seller, shipping and buying option details" box of an offer, e.g.
    ("Fulfilled by", "Amazon") for fulfillerInfoFeature, ("Sold by", "Padimu") for merchantInfoFeature."""
    # "<div id=": the same name also appears as data-csa-c-slot-id="..." inside the tag itself
    m = re.search(rf'<div id="{name}_feature_div"(.*?)(?:<div id="\w+_feature_div"|$)', block, re.S)
    if not m:
        return "", ""
    label = re.search(r'a-color-tertiary">(.*?)</span>', m.group(1), re.S)
    value = re.search(r'offer-display-feature-text-message">(.*?)</span>', m.group(1), re.S)
    return (clean(label.group(1)) if label else ""), (clean(value.group(1)) if value else "")


def shipped_by_amazon(block, via=None, blind=None):
    """True when Amazon ships this offer itself from its UAE warehouses: "Fulfilled by Amazon" (whoever sells it) or
    "Shipper / Seller Amazon.ae". Those are the offers an account gets at the "fastest delivery" date. Not the seller's
    identity (which never decides anything, Hoodo, 10 Nov): the same seller can have both kinds of offers."""
    label, who = _feature(block, "fulfillerInfoFeature")
    if label.lower().startswith("fulfilled") and who.lower().startswith("amazon"):
        return True
    label2, who2 = _feature(block, "merchantInfoFeature")
    if label or label2:
        return label2.lower().startswith("shipper") and who2.lower() == "amazon.ae"
    # Spare reading (neither box found: Amazon renamed them): the same two wordings in the text of the offer. "Amazon US",
    # "Amazon UK" (imports) and "Delivered by Amazon.ae" (the seller ships) still do not count.
    text = clean(block)
    found = bool(re.search(r"Fulfilled by\s*:?\s*Amazon\b(?!\s*(?:US|UK|Global)\b)", text) or
                 re.search(r"Shipper\s*/\s*Seller\s*:?\s*Amazon\.ae\b", text))
    worded = re.search(r"Fulfilled by|Shipper\s*/\s*Seller|Sold by|Ships from|Dispatched from|Delivered by", text)
    if worded and via is not None:
        via.append("shipper")
    if not worded and blind is not None:
        blind.append("shipper")  # nothing says who ships: the "fastest date" rule cannot apply to this offer
    return found


def parse_seller(block):
    """Name of the seller of this buy box / offer, or "" if not found."""
    m = re.search(r'id="sellerProfileTriggerId"[^>]*>\s*([^<]+?)\s*<', block)
    if m:
        return m.group(1).strip(" .")
    i = block.find('id="merchantInfoFeature_feature_div"')
    text = clean(block[i:i + 3000]) if i >= 0 else ""
    return "Amazon.ae" if "Amazon.ae" in text else ""


def buybox_offers(html, via=None):
    """The offers of the buy box as HTML fragments, in the order Amazon shows them (the featured one first). Empty list when
    the page has no desktop buy box."""
    i = html.find('id="desktop_buybox"')
    if i < 0:
        i = html.find('id="buybox"')  # spare: the inner box, should Amazon rename the outer one
        if i >= 0 and via is not None:
            via.append("buybox")
    if i < 0:
        return []
    end = html.find('id="wishlistButtonStack"', i)
    zone = html[i:end if end >= 0 else i + 3 * SEGMENT_MAX]
    starts = [m.start() for m in NEW_ROW_RE.finditer(zone)]
    if not starts:
        return [zone[:3 * SEGMENT_MAX]]  # a single offer, no accordion
    others = [m.start() for m in ROW_RE.finditer(zone)]  # the start of any row ends the previous offer
    segments = []
    for s in starts:
        nxt = min([p for p in others if p > s] + [len(zone), s + SEGMENT_MAX])
        segments.append(zone[s:nxt])
    return segments


AVAIL_TEXT_RE = re.compile(
    r"only\s+\d+\s+left in stock(?:\s*-\s*order soon)?\.?|currently unavailable\.?|temporarily out of stock\.?|"
    r"out of stock\.?|(?:available|in stock)\s+(?:on|from|soon)\b[^.]{0,30}|in stock\b|"
    r"usually (?:ships|dispatched) within [\w ]{1,25}", re.I)
OFF_RE = re.compile(r"unavailable|out of stock|not yet released|pre-?order|(?:available|in stock) (?:on|from|soon)|temporarily",
                    re.I)


def availability_of(seg, via=None):
    """The stock line of an offer ("In Stock", "Only 2 left in stock - order soon.", "Currently unavailable.")."""
    m = re.search(r'\sid="availability"[^>]*>(.*?)</div>', seg, re.S)
    if m and clean(m.group(1)):
        return clean(m.group(1))
    # Spare reading: the same wording, looked for in the availability box of the buy box, then in the text of the offer.
    i = seg.find("availabilityInsideBuyBox_feature_div")
    for text in ((clean(seg[i:i + 4000]) if i >= 0 else ""), clean(seg)):
        found = AVAIL_TEXT_RE.search(text)
        if found:
            if via is not None:
                via.append("stock")
            return found.group(0).strip()
    return ""


def parse_offer(seg, today):
    """Facts of one offer: price, stock line, quantity limits, delivery, seller.

    Every fact has a spare reading for the day Amazon changes its page (validated on real pages, see PROTOCOLE section 13):
    "via" lists the facts that needed it. "blind" lists the facts found by neither reading on an offer that can be bought
    (a rule is then silently off: low stock, fastest date). "doubt" says the offer itself could not be understood: it does
    not look buyable, and nothing on the page says it is unavailable. Such an offer is never read as out of stock."""
    via, blind = [], []
    price = parse_price(seg, via)
    avail = availability_of(seg, via)
    left = re.search(r"only\s+(\d+)\s+left in stock", avail, re.I)
    cart = 'id="add-to-cart-button"' in seg
    if not cart and ('name="submit.add-to-cart"' in seg or 'id="buy-now-button"' in seg):
        cart = True
        via.append("cart")
    off = OFF_RE.search(avail) or 'id="outOfStock"' in seg or "buybox-see-all-buying-choices" in seg
    q = re.search(r'<select[^>]*\bid="quantity"[^>]*>(.*?)</select>', seg, re.S)
    options = [int(x) for x in re.findall(r'<option[^>]*value="(\d+)"', q.group(1))] if q else []
    in_stock = price is not None and cart and not off
    ships = shipped_by_amazon(seg, via, blind if in_stock else None)
    promises = delivery_options(seg)
    if not promises:
        promises = delivery_options_text(seg)
        if promises:
            via.append("delivery")
    days, text, fee = pick_delivery(promises, today, amazon=ships)
    doubt = None
    if not in_stock and not off:
        doubt = "price" if cart else "cart" if price is not None else "offer"
    if in_stock and not avail:
        blind.append("stock")  # no stock line at all: "Only N left" cannot be seen
    return {"aed": price, "inStock": bool(in_stock), "availability": avail[:80],
            "seller": parse_seller(seg), "amazonShips": ships, "stockLeft": int(left.group(1)) if left else None,
            "maxQty": max(options) if options else None, "deliveryText": text, "sourceDays": days,
            "storeDays": None if days is None else days + EXTRA_DAYS, "deliveryFee": fee,
            # every promise as the page words it ("free: Saturday, 14 November | fastest: Tomorrow, 12 November"), for the
            # reports and the order alerts: Hoodo can compare with what her account shows
            "promises": " | ".join(f"{o['kind']}: {o['text']}" for o in promises)[:160],
            "via": via, "blind": blind, "doubt": doubt}


def page_asin(html):
    """(ASIN the page is about, how many markers agree). The canonical link, the hidden ASIN input and "currentAsin" are the
    markers; they all carry the requested ASIN on a normal page."""
    marks = []
    for pat in (r'<link[^>]*rel="canonical"[^>]*href="[^"]*?/dp/([A-Z0-9]{10})',
                r'<input[^>]*\bid="ASIN"[^>]*\bvalue="([A-Z0-9]{10})"',
                r'"currentAsin"\s*:\s*"([A-Z0-9]{10})"'):
        m = re.search(pat, html)
        if m:
            marks.append(m.group(1))
    if not marks:
        return None, 0
    best = max(set(marks), key=marks.count)
    return best, marks.count(best)


def location_of(html):
    """Delivery location shown by the page ("Deliver to Dubai, Ras Al Khor"), or None when the page does not say."""
    m = re.search(r'contextualIngressPtLabel_deliveryShortLine"[^>]*>([^<]*)<', html) or \
        re.search(r'id="glow-ingress-line2"[^>]*>\s*([^<]*)<', html)
    return clean(m.group(1)) if m and clean(m.group(1)) else None


def variation_of(html):
    """The option the page shows as selected (shade, size...), joined with " / "."""
    vals = [clean(v) for v in re.findall(r'id="inline-twister-expanded-dimension-text-[^"]*"[^>]*>(.*?)</', html, re.S)]
    return " / ".join(v for v in vals if v) or None


def title_of(html):
    m = re.search(r'id="productTitle"[^>]*>(.*?)</span>', html, re.S) or \
        re.search(r'<(h1|span)[^>]*\bid="title"[^>]*>(.*?)</\1>', html, re.S) or re.search(r"<title>(.*?)</title>", html, re.S)
    return clean(m.group(m.lastindex)) if m else None


def gone_page(html):
    """A listing that no longer exists (HTTP 404 body): no product title and Amazon's own "Page Not Found" wording."""
    return 'id="productTitle"' not in html and bool(
        re.search(r"<title>\s*Page Not Found\s*</title>|not a functioning page", html, re.I))


def parse(html, today, asin=None):
    """Facts of a product page. asin = the ASIN that was asked for: a page about another ASIN is flagged "redirect".
    Returns {"error": ...} for a page that cannot be read (never to be taken as "out of stock"), a page dict with "gone": True
    for a removed listing, or the featured offer's facts + "offers" (all the offers, featured first)."""
    via = []
    shown, agree = page_asin(html)
    if 'id="productTitle"' not in html:  # blocked, empty or partial page: never read it as out of stock
        if gone_page(html):
            return {"gone": True, "aed": None, "inStock": False, "availability": "page removed", "seller": "",
                    "stockLeft": None, "deliveryText": None, "sourceDays": None, "storeDays": None}
        # Spare: a product page whose title block was renamed still carries its ASIN markers and its title section.
        if not (agree >= 2 and ('id="titleSection"' in html or 'id="title_feature_div"' in html or 'id="title"' in html)):
            return {"error": "captcha" if "captcha" in html.lower() else "no product page"}
        via.append("title")
    segments = buybox_offers(html, via)
    if not segments:
        return {"error": "no buy box"}
    where = location_of(html)
    if where and CITY.lower() not in where.lower():
        return {"error": "location", "location": where}  # a delivery date for another address is worth nothing
    offers = [parse_offer(seg, today) for seg in segments]
    if offers[0]["doubt"]:
        # The featured offer cannot be understood (Amazon changed its page, or the page did not finish loading): the page
        # counts as NOT READ. It is read again; the variant is neither hidden as "out of stock" on a guess nor confirmed.
        return {"error": "layout: " + offers[0]["doubt"], "layout": offers[0]["doubt"]}
    page = {**offers[0], "offers": offers, "offer": 0, "location": where, "title": title_of(html),
            "variation": variation_of(html)}
    page["pageVia"] = via  # spare readings used for the page itself (title, buy box); the offers carry their own "via"
    page["pageBlind"] = [] if where else ["location"]  # the page does not say where it delivers: the city is unchecked
    page["asin"] = shown
    if asin and shown and shown != asin and agree >= 2:
        # The page is about ANOTHER item (the listing was merged or replaced: the shade or the size is not the same).
        # Only the ASIN says so; a changed title, description, seller or shade label never does.
        page.update({"redirect": shown, "inStock": False, "aed": None, "sourceDays": None, "storeDays": None,
                     "stockLeft": None, "deliveryText": None, "deliveryFee": 0.0, "offers": []})
    return page
