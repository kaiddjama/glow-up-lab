#!/usr/bin/env python3
"""Amazon.ae price and stock sync for a Shopify store.

Usage: python3 -I amazon_sync.py results_dir
Settings come from environment variables (GitHub Actions secrets and variables): SHOPIFY_STORE and
SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET (or SHOPIFY_TOKEN); PRICE_FORMULA (kept out of the code). Optional: DRY_RUN=1 (read and report only), LIMIT=n, SHARD=i/n, DELAY, FETCHER=browser (headless Chromium set to Dubai, see browser_fetch.py).
Without credentials the script does nothing and exits cleanly.

For every active variant that has an ASIN (SKU "B0…" / "AMZ-B0…" or a product metafield) it reads the Amazon.ae
page (price, stock, delivery date) and updates the price, the "continue selling" setting and the
supplier.* metafields. A page Amazon blocks leaves the variant unchanged. Price changes above 150 % are only
reported. Draft products tagged "livraison-lente" are republished when their delivery time allows it.
"""
import datetime as dt
import json
import math
import os
import random
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

API = "2025-07"
try:  # one secret "a,b,c" holds the price formula, so masking hides it as a whole in the logs
    MARGIN_CUSTOMS, SHIPPING_AED_PER_KG, AED_TO_FDJ = (float(x) for x in os.environ.get("PRICE_FORMULA", "").split(","))
except ValueError:
    MARGIN_CUSTOMS = SHIPPING_AED_PER_KG = AED_TO_FDJ = 0.0
DEFAULT_WEIGHT_G = 200
MAX_CHANGE = 1.50  # bigger jumps usually mean a misread page or a wrong listing: held for review
EXTRA_DAYS = 2
MAX_DAYS = 7  # Amazon.ae or brand store: delivery to Dubai later than this counts as out of stock
MAX_DAYS_OTHER = 2  # any other seller: kept only if it delivers within 2 days
STOCK_GUARD = 0.25  # share of read variants that may newly go Épuisé in one run before stock changes are held
SELLER_GUARD = 0.25  # share of pages read that may newly go Épuisé because of the seller rule in one run
SELLER_RULE = os.environ.get("SELLER_RULE", "0") == "1"  # off since 22 Oct (seller rule removed); SELLER_RULE=1 switches it back on
EXEMPT_TAGS = set(os.environ.get(
    "EXEMPT_TAGS", "sub:ch-accessoires,sub:mk-accessoires,sub:cp-accessoires,sub:bb-repas,sub:en-repas").split(","))
VERIFIED = ("amazon", "brand", "allowlist")
PARK_TAG = "livraison-lente"  # draft + this tag = set aside for slow delivery, republished by this script
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
ASIN_RE = re.compile(r"\b(?:AMZ-)?(B0[A-Z0-9]{8})\b")
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}

PRODUCTS_Q = """query($after:String,$q:String!){ products(first:50, after:$after, query:$q){
  pageInfo{hasNextPage endCursor}
  nodes{ id handle vendor status tags
    ref: metafield(namespace:"internal", key:"supplier_ref"){value}
    spreadr: metafield(namespace:"global", key:"spreadr-asin"){value}
    weight: metafield(namespace:"internal", key:"weight_g"){value}
    variants(first:100){ nodes{ id title sku price inventoryPolicy
      range: metafield(namespace:"supplier", key:"delivery_range"){value}
      inventoryItem{ measurement{ weight{ value unit } } } } } } } }"""
PRICES_M = """mutation($p:ID!,$v:[ProductVariantsBulkInput!]!){
  productVariantsBulkUpdate(productId:$p, variants:$v){ userErrors{field message} } }"""
STATUS_M = """mutation($p:ProductUpdateInput!){productUpdate(product:$p){userErrors{field message}}}"""
TAGS_ADD_M = """mutation($id:ID!,$t:[String!]!){tagsAdd(id:$id, tags:$t){userErrors{field message}}}"""
TAGS_REMOVE_M = """mutation($id:ID!,$t:[String!]!){tagsRemove(id:$id, tags:$t){userErrors{field message}}}"""
META_M = """mutation($m:[MetafieldsSetInput!]!){metafieldsSet(metafields:$m){userErrors{field message}}}"""


def token():
    """SHOPIFY_TOKEN if set, else a short-lived token from a Dev Dashboard app (client credentials)."""
    if not os.environ.get("SHOPIFY_TOKEN"):
        req = urllib.request.Request(
            f"https://{os.environ['SHOPIFY_STORE']}/admin/oauth/access_token",
            data=urllib.parse.urlencode({"grant_type": "client_credentials",
                                         "client_id": os.environ["SHOPIFY_CLIENT_ID"],
                                         "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"]}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=30) as r:
            os.environ["SHOPIFY_TOKEN"] = json.load(r)["access_token"]
    return os.environ["SHOPIFY_TOKEN"]


def gql(query, variables):
    for attempt in range(1, 11):
        req = urllib.request.Request(
            f"https://{os.environ['SHOPIFY_STORE']}/admin/api/{API}/graphql.json",
            data=json.dumps({"query": query, "variables": variables}).encode(),
            headers={"Content-Type": "application/json",
                     "X-Shopify-Access-Token": token()})
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.load(r)
        throttled = any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in res.get("errors") or [])
        if throttled and attempt < 10:  # several shards share the store's query budget: wait for it to refill
            time.sleep(min(60, 3 * attempt) + random.uniform(0, 3))
            continue
        if res.get("errors"):
            raise RuntimeError(res["errors"])
        return res["data"]


def load_variants():
    rows = []
    for search, parked in (("status:active", False), (f"status:draft tag:{PARK_TAG}", True)):
        rows += load_rows(search, parked)
    return rows


def load_rows(search, parked):
    rows, after = [], None
    while True:
        data = gql(PRODUCTS_Q, {"after": after, "q": search})["products"]
        for p in data["nodes"]:
            single = len(p["variants"]["nodes"]) == 1
            product_asin = None
            for src in (p.get("spreadr"), p.get("ref")):
                m = src and ASIN_RE.search(src["value"])
                if m:
                    product_asin = m.group(1)
                    break
            for v in p["variants"]["nodes"]:
                m = ASIN_RE.search(v.get("sku") or "")
                asin = m.group(1) if m else (product_asin if single else None)
                if not asin:
                    continue
                grams = None
                if p.get("weight"):
                    grams = float(p["weight"]["value"])
                else:
                    w = ((v.get("inventoryItem") or {}).get("measurement") or {}).get("weight") or {}
                    factor = {"GRAMS": 1, "KILOGRAMS": 1000, "POUNDS": 453.6, "OUNCES": 28.35}.get(w.get("unit"))
                    if factor and w.get("value"):
                        grams = float(w["value"]) * factor
                rows.append({"productId": p["id"], "handle": p["handle"], "vendor": p.get("vendor") or "",
                             "exempt": bool(EXEMPT_TAGS & set(p.get("tags") or [])),
                             "variantId": v["id"],
                             "variant": v["title"], "asin": asin, "price": float(v["price"]),
                             "policy": v["inventoryPolicy"], "grams": grams or DEFAULT_WEIGHT_G,
                             "range": (v.get("range") or {}).get("value"),
                             "parked": parked, "nvariants": len(p["variants"]["nodes"])})
        if not data["pageInfo"]["hasNextPage"]:
            return rows
        after = data["pageInfo"]["endCursor"]


READER = None  # set to a browser_fetch.BrowserReader when FETCHER=browser


def fetch(asin):
    if READER:
        return READER.get(f"https://www.amazon.ae/dp/{asin}?language=en_AE")
    req = urllib.request.Request(f"https://www.amazon.ae/dp/{asin}?language=en_AE",
                                 headers={"User-Agent": UA, "Accept-Language": "en-AE,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def days_until(text, today):
    t = text.lower()
    if t.startswith("today") or re.search(r"\b\d+\s*(hr|hrs|hour|hours|min|mins|minutes)\b", t):
        return 0  # same day, including Amazon's "in 1 hr 30 mins" express delivery
    found = re.findall(r"(\d{1,2})\s+([a-z]+)", t)
    if not found and "tomorrow" in t:
        return 1
    if not found:
        return None
    day, month = found[-1]
    month = next((full for full in MONTHS if len(month) >= 3 and full.startswith(month[:3])), None)  # "Oct" or "October"
    if not month:
        return None
    d = dt.date(today.year, MONTHS[month], int(day))
    if d < today:
        d = dt.date(today.year + 1, MONTHS[month], int(day))
    return (d - today).days


def parse_price(html):
    """AED price of the buy box, or None."""
    i = html.find("apex-pricetopay-value")  # the price to pay; its a-offscreen text is often empty
    if i >= 0:
        w = re.search(r'a-price-whole">([\d,]+)', html[i:i + 600])
        f = re.search(r'a-price-fraction">(\d+)', html[i:i + 800])
        if w:
            return float(w.group(1).replace(",", "") + "." + (f.group(1) if f else "0"))
    for anchor in ('id="corePriceDisplay_desktop_feature_div"', 'id="corePrice_feature_div"',
                   'id="corePrice_desktop"', 'id="apex_desktop"'):
        i = html.find(anchor)
        if i < 0:
            continue
        block = html[i:i + 6000]
        m = re.search(r'a-offscreen">\s*(?:AED|د\.إ\.?)\s*&nbsp;?\s*([\d,]+\.?\d*)', block) or \
            re.search(r'a-offscreen">[^<\d]*([\d,]+\.\d{2})', block)
        if m:
            return float(m.group(1).replace(",", ""))
        w = re.search(r'a-price-whole">([\d,]+)', block)
        if w:
            f = re.search(r'a-price-fraction">(\d+)', block[w.end():w.end() + 200])
            return float(w.group(1).replace(",", "") + "." + (f.group(1) if f else "0"))
    m = re.search(r'"priceAmount":\s*([\d.]+)', html)
    return float(m.group(1)) if m else None


def parse(html, today):
    if 'id="productTitle"' not in html:  # blocked, empty or partial page: never read it as out of stock
        return {"error": "captcha" if "captcha" in html.lower() else "no product page"}
    avail = re.search(r'id="availability".*?</div>', html, re.S)
    avail_text = re.sub(r"<[^>]+>|\s+", " ", avail.group(0)).strip() if avail else ""
    price = parse_price(html)
    in_stock = price is not None and not re.search(r"unavailable|out of stock", avail_text, re.I)
    # The buy box lists the standard date AND, when offered, a faster one ("Rush delivery Today by 3 PM",
    # same-day or express); the fastest counts.
    i = html.find('id="desktop_buybox"')
    zone = html[i:i + 30000] if i >= 0 else html
    options = re.findall(r'data-csa-c-delivery-time="([^"]*)"', zone)
    scored = [(days_until(o, today), o) for o in options]
    scored = [x for x in scored if x[0] is not None]
    src, delivery = min(scored) if scored else (None, options[0] if options else None)
    return {"aed": price, "inStock": in_stock, "availability": avail_text[:80], "seller": parse_seller(html),
            "deliveryText": delivery, "sourceDays": src, "storeDays": None if src is None else src + EXTRA_DAYS}


def fetch_offers(asin):
    """The "all offers" list of a listing (new condition)."""
    url = (f"https://www.amazon.ae/gp/product/ajax/ref=dp_aod_NEW_mbc?asin={asin}&m=&qid=&smid=&sourcecja="
           "&condition=NEW&experienceId=aodAjaxMain&pc=dp&language=en_AE")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-AE,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_offers(html, vendor, today):
    """Fastest verified new offer (Amazon.ae, the brand, an authorised seller) in the offers list, or None."""
    best = None
    for block in html.split('id="aod-offer"')[1:]:
        head = re.sub(r"<[^>]+>|\s+", " ", block[:3000])
        if re.search(r"\b(used|renewed|refurbished)\b", head, re.I):
            continue
        m = re.search(r'id="aod-offer-soldBy".*?<a[^>]*>\s*([^<]+?)\s*</a>', block, re.S) or \
            re.search(r'id="aod-offer-soldBy".*?class="a-size-small a-color-base">\s*([^<]+?)\s*<', block, re.S)
        seller = m.group(1).strip(" .") if m else ""
        if seller_class(seller, vendor) not in VERIFIED:
            continue
        pm = re.search(r'a-offscreen">\s*(?:AED|د\.إ\.?)\s*(?:&nbsp;)?\s*([\d,]+\.?\d*)', block)
        scored = [(days_until(o, today), o) for o in re.findall(r'data-csa-c-delivery-time="([^"]*)"', block)]
        scored = [x for x in scored if x[0] is not None]
        if not pm or not scored:
            continue
        days, text = min(scored)
        offer = {"aed": float(pm.group(1).replace(",", "")), "seller": seller, "sourceDays": days,
                 "deliveryText": text, "storeDays": days + EXTRA_DAYS, "inStock": True}
        if best is None or (offer["sourceDays"], offer["aed"]) < (best["sourceDays"], best["aed"]):
            best = offer
    return best


def parse_seller(html):
    """Name of the buy-box seller, or "" if not found."""
    m = re.search(r'id="sellerProfileTriggerId"[^>]*>\s*([^<]+?)\s*<', html)
    if m:
        return m.group(1).strip(" .")
    i = html.find('id="merchantInfoFeature_feature_div"')
    block = re.sub(r"<[^>]+>|\s+", " ", html[i:i + 3000]) if i >= 0 else ""
    return "Amazon.ae" if "Amazon.ae" in block else ""


def allowlist():
    """authorised-sellers.json next to this script: {"any_brand": ["seller", ...], "by_brand": {"brand": ["seller"]}}."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "authorised-sellers.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


ALLOW = allowlist()
BRAND_STOP = {"the", "and", "paris", "beauty", "professional", "professionnel", "labs", "lab", "natural", "naturals",
              "nutrition", "health", "care", "skin", "skincare", "hair", "baby", "kids", "products", "official"}


def plain(text):
    """Lower case, accents removed (L'Oréal -> l'oreal)."""
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().strip().lower()


def seller_class(seller, vendor):
    """amazon / brand / allowlist (verified), third_party, or unknown when the page gave no seller name."""
    s = plain(seller)
    if not s:
        return "unknown"
    if "amazon" in s:
        return "amazon"
    v = plain(vendor)
    tokens = [w for w in re.findall(r"[a-z0-9]+", v) if len(w) > 2 and w not in BRAND_STOP]
    if tokens and tokens[0] in s:  # "Medicube Official Store", "CeraVe" ...
        return "brand"
    names = [plain(n) for n in ALLOW.get("any_brand", []) + ALLOW.get("by_brand", {}).get(v, [])]
    if s in names:
        return "allowlist"
    return "third_party"


def official(seller, vendor):
    """Sold by Amazon itself, by the brand's own store or by an authorised seller."""
    return seller_class(seller, vendor) in VERIFIED


def seller_blocked(page, row):
    """Authenticity rule: a non-verified seller is not sold (exempt: unbranded accessories)."""
    return (SELLER_RULE and not row.get("exempt") and not page.get("error")
            and seller_class(page.get("seller"), row["vendor"]) == "third_party")


def sellable(page, row):
    if page.get("held"):  # seller not confirmed authentic: stays Épuisé, see seller-hold.json
        return False
    days = page.get("sourceDays")
    if seller_blocked(page, row):
        return False
    limit = MAX_DAYS if official(page.get("seller", ""), row["vendor"]) else MAX_DAYS_OTHER
    return page["inStock"] and days is not None and days <= limit


def delivery_range(page):
    days = page.get("sourceDays")
    return "standard" if days is not None and days <= MAX_DAYS_OTHER else "3-10"


def formula(aed, grams):
    fdj = (aed * MARGIN_CUSTOMS + grams / 1000 * SHIPPING_AED_PER_KG) * AED_TO_FDJ
    return int(math.ceil(fdj / 50) * 50)


def main():
    global SELLER_RULE
    if not (os.environ.get("SHOPIFY_STORE") and (os.environ.get("SHOPIFY_TOKEN") or os.environ.get("SHOPIFY_CLIENT_SECRET"))):
        print("No Shopify credentials set: nothing to do.")
        return
    if not (MARGIN_CUSTOMS and SHIPPING_AED_PER_KG and AED_TO_FDJ):
        sys.exit("PRICE_FORMULA secret is missing or malformed.")
    outdir = sys.argv[1]
    os.makedirs(outdir, exist_ok=True)
    dry = os.environ.get("DRY_RUN") == "1"
    delay = float(os.environ.get("DELAY", "8"))
    today = dt.date.today()
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = load_variants()
    asins = sorted({r["asin"] for r in rows})
    if os.environ.get("LIMIT"):
        n_max = int(os.environ["LIMIT"])  # an evenly spread sample, not just the first ASINs
        asins = asins[::max(1, len(asins) // n_max)][:n_max]
    if os.environ.get("SHARD"):  # "i/n": this process reads only every n-th ASIN, starting at i (parallel runs)
        i, n = (int(x) for x in os.environ["SHARD"].split("/"))
        asins = asins[i::n]
    print(f"{len(rows)} variants with an ASIN, {len(asins)} Amazon pages to read")
    global READER
    if os.environ.get("FETCHER") == "browser":  # real headless browser set to a Dubai delivery address
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I does not add the script folder
        import browser_fetch
        try:
            READER = browser_fetch.BrowserReader().start()
        except (browser_fetch.LocationLost, browser_fetch.Captcha) as e:
            sys.exit(f"Browser could not start on Amazon.ae with a Dubai address ({e}): nothing changed.")
        print("Browser reader started, delivery location:", READER.location_text())

    vendor_of = {r["asin"]: r["vendor"] for r in rows}
    exempt_asin = {r["asin"] for r in rows if r["exempt"]}
    pages, blocked_in_a_row = {}, 0
    for n, asin in enumerate(asins, 1):
        try:
            pages[asin] = parse(fetch(asin), today)
            pg = pages[asin]
            if (SELLER_RULE and asin not in exempt_asin and not pg.get("error")
                    and seller_class(pg.get("seller"), vendor_of[asin]) == "third_party"):
                time.sleep(delay)
                try:  # the buy box is a third party: look for an Amazon.ae / brand / authorised offer instead
                    alt = parse_offers(fetch_offers(asin), vendor_of[asin], today)
                except Exception:
                    alt = None
                if alt:
                    pg["buyBoxSeller"] = pg["seller"]
                    pg.update(alt)
        except Exception as e:  # network error, 404 = listing removed
            if READER and type(e).__name__ == "LocationLost":
                print(f"{e}: stopping after {n - 1} pages, rest left unchanged")
                break
            pages[asin] = {"error": str(e)[:100]}
        blocked_in_a_row = blocked_in_a_row + 1 if pages[asin].get("error") == "captcha" else 0
        if blocked_in_a_row >= 5:
            print(f"Amazon is showing CAPTCHAs: stopping after {n} pages, rest left unchanged")
            break
        time.sleep(delay + random.uniform(0, delay / 2))

    if READER:
        READER.close()
    hold_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seller-hold.json")
    held = set(json.load(open(hold_file)).get("asins", [])) if os.path.exists(hold_file) else set()
    for asin in held & set(pages):
        pages[asin]["held"] = True
    report = {"checkedAt": now, "dryRun": dry, "changes": [], "skipped": [], "errors": [],
              "republished": [], "stillParked": [], "parkedNow": [], "sellerFlags": [], "sellerGuardTripped": False}
    by_product, range_fields = {}, []
    # seller rule guard: too many new Épuisé because of the seller alone = probably a misread page
    read = [r for r in rows if pages.get(r["asin"]) and not pages[r["asin"]].get("error")]
    newly = [r for r in read if r["policy"] == "CONTINUE" and seller_blocked(pages[r["asin"]], r)]
    if SELLER_RULE and len(read) >= 20 and len(newly) > SELLER_GUARD * len(read):
        report["sellerGuardTripped"] = True
        print(f"Seller rule not applied: {len(newly)} of {len(read)} variants would newly go Épuisé (guard {SELLER_GUARD:.0%}).")
        flagged_rule, SELLER_RULE = True, False
    else:
        flagged_rule = False
    for r in read:
        pg = pages[r["asin"]]
        cls = seller_class(pg.get("seller"), r["vendor"])
        if cls == "third_party" or pg.get("buyBoxSeller"):
            report["sellerFlags"].append({
                "handle": r["handle"], "variant": r["variant"], "asin": r["asin"], "vendor": r["vendor"],
                "seller": pg.get("buyBoxSeller") or pg.get("seller"), "class": cls, "aed": pg.get("aed"),
                "days": pg.get("sourceDays"),
                "action": ("exempt (accessoire)" if r["exempt"] else
                           "offre officielle trouvée: " + pg["seller"] if pg.get("buyBoxSeller") else
                           "signalé seulement (garde-fou)" if flagged_rule else "Épuisé")})
    # Safety nets: a page in stock with no delivery date (location not read, partial page) says nothing about
    # delivery, so the variant keeps its current setting; and if too many variants would newly go Épuisé in
    # one run, the page reading is probably off (wrong location, blocking): no stock change is made at all.
    def no_date(p):
        return bool(p.get("inStock")) and p.get("sourceDays") is None and not p.get("held")

    live = [r for r in rows if not r["parked"] and pages.get(r["asin"]) and not pages[r["asin"]].get("error")]
    newly_out = [r for r in live if r["policy"] == "CONTINUE" and not no_date(pages[r["asin"]])
                 and not sellable(pages[r["asin"]], r)]
    stock_guard = len(live) >= 20 and len(newly_out) > STOCK_GUARD * len(live)
    report["stockGuardTripped"] = stock_guard
    report["noDeliveryDate"] = sum(no_date(pages[r["asin"]]) for r in live)
    if stock_guard:
        print(f"Stock guard: {len(newly_out)} of {len(live)} variants would newly go Épuisé, no stock change made.")
    # set-aside (draft) products come back as soon as one of their variants is sellable
    revive = {r["productId"] for r in rows if r["parked"] and pages.get(r["asin"])
              and not pages[r["asin"]].get("error") and sellable(pages[r["asin"]], r)}
    for r in rows:
        page = pages.get(r["asin"])
        if not page:
            continue
        if r["parked"] and r["productId"] not in revive:
            if page.get("error"):
                report["errors"].append({"asin": r["asin"], "handle": r["handle"], "error": page["error"]})
            else:
                report["stillParked"].append({"handle": r["handle"], "asin": r["asin"], "aed": page["aed"],
                                              "inStock": page["inStock"], "seller": page["seller"],
                                              "delivery": page["deliveryText"], "days": page["sourceDays"]})
            continue
        if page.get("error"):
            report["errors"].append({"asin": r["asin"], "handle": r["handle"], "error": page["error"]})
            continue
        upd = {"id": r["variantId"]}
        if stock_guard or no_date(page):
            new_policy = r["policy"]
        else:
            new_policy = "CONTINUE" if sellable(page, r) else "DENY"
        if new_policy != r["policy"]:
            upd["inventoryPolicy"] = new_policy
        if page["aed"] is not None and new_policy == "CONTINUE":
            new = formula(page["aed"], r["grams"])
            if r["parked"] or abs(new - r["price"]) >= 50:  # a republished product always gets a fresh price
                if r["price"] and abs(new - r["price"]) / r["price"] > MAX_CHANGE:
                    report["skipped"].append({"handle": r["handle"], "variant": r["variant"], "asin": r["asin"],
                                              "aed": page["aed"], "now": r["price"], "formula": new})
                else:
                    upd["price"] = str(new)
        if len(upd) > 1:
            report["changes"].append({"handle": r["handle"], "variant": r["variant"], "asin": r["asin"],
                                      "aed": page["aed"], "oldPrice": r["price"], **upd})
            by_product.setdefault(r["productId"], []).append(upd)
        if new_policy == "CONTINUE" and page.get("sourceDays") is not None:
            rng = delivery_range(page)
            if rng != r["range"]:
                range_fields.append({"ownerId": r["variantId"], "namespace": "supplier", "key": "delivery_range",
                                     "type": "single_line_text_field", "value": rng})
                report["changes"].append({"handle": r["handle"], "variant": r["variant"], "asin": r["asin"],
                                          "deliveryRange": rng})
        agg = by_product.setdefault(("meta", r["productId"]), [])
        agg.append({**page, "ok": new_policy == "CONTINUE", "sellerClass": seller_class(page.get("seller"), r["vendor"])})

    # ACTIVE products whose variants are all in stock but too slow: optionally set aside instead of Épuisé
    if os.environ.get("SLOW_TO_DRAFT") == "1":
        for pid in {r["productId"] for r in rows if not r["parked"]}:
            mine = [r for r in rows if r["productId"] == pid]
            ps = [pages.get(r["asin"]) for r in mine]
            if (len(mine) == mine[0]["nvariants"] and all(p and not p.get("error") for p in ps)
                    and all(p["inStock"] and not sellable(p, r) for p, r in zip(ps, mine))):
                report["parkedNow"].append({"handle": mine[0]["handle"], "asin": mine[0]["asin"],
                                            "delivery": ps[0]["deliveryText"], "seller": ps[0]["seller"]})

    errors = 0
    if not dry:
        for pid, ups in by_product.items():
            if isinstance(pid, tuple):
                continue
            res = gql(PRICES_M, {"p": pid, "v": ups})["productVariantsBulkUpdate"]["userErrors"]
            errors += len(res)
            for e in res:
                print("price/stock error:", pid, e)
        fields = []
        for key, plist in by_product.items():
            if not isinstance(key, tuple):
                continue
            pid = key[1]
            any_stock = any(p["ok"] for p in plist)
            days = [p["storeDays"] for p in plist if p["ok"] and p["storeDays"] is not None]
            fields.append({"ownerId": pid, "namespace": "supplier", "key": "in_stock",
                           "type": "boolean", "value": "true" if any_stock else "false"})
            fields.append({"ownerId": pid, "namespace": "supplier", "key": "checked_at",
                           "type": "date_time", "value": now})
            seen = next((p for p in plist if p.get("seller")), None)
            if seen:
                fields.append({"ownerId": pid, "namespace": "supplier", "key": "seller",
                               "type": "single_line_text_field", "value": seen["seller"][:100]})
                fields.append({"ownerId": pid, "namespace": "supplier", "key": "seller_class",
                               "type": "single_line_text_field", "value": seen["sellerClass"]})
            if days:
                fields.append({"ownerId": pid, "namespace": "supplier", "key": "delivery_days",
                               "type": "number_integer", "value": str(min(days))})
        fields += range_fields
        for pid in revive:  # back online: ACTIVE, tag removed (after the prices and stock above)
            for q, vars_ in ((STATUS_M, {"p": {"id": pid, "status": "ACTIVE"}}),
                             (TAGS_REMOVE_M, {"id": pid, "t": [PARK_TAG]})):
                res = gql(q, vars_)
                errs = next(iter(res.values()))["userErrors"]
                errors += len(errs)
                for e in errs:
                    print("republish error:", pid, e)
        for item in report["parkedNow"]:
            pid = next(r["productId"] for r in rows if r["handle"] == item["handle"])
            for q, vars_ in ((STATUS_M, {"p": {"id": pid, "status": "DRAFT"}}),
                             (TAGS_ADD_M, {"id": pid, "t": [PARK_TAG]})):
                errs = next(iter(gql(q, vars_).values()))["userErrors"]
                errors += len(errs)
        for i in range(0, len(fields), 25):
            res = gql(META_M, {"m": fields[i:i + 25]})["metafieldsSet"]["userErrors"]
            errors += len(res)

    report["republished"] = sorted({r["handle"] for r in rows if r["productId"] in revive})
    path = os.path.join(outdir, f"sync-{now[:13].replace(':', '')}.json")
    json.dump(report, open(path, "w"), indent=1, ensure_ascii=False)
    reasons = {}
    for e in report["errors"]:
        k = str(e.get("error") if isinstance(e, dict) else e)[:40]
        reasons[k] = reasons.get(k, 0) + 1
    if reasons:
        print("Pages not read, by reason:", reasons)
    prices = sum("price" in c for c in report["changes"])
    stock = sum("inventoryPolicy" in c for c in report["changes"])
    days_seen = {}
    for r in live:
        d = pages[r["asin"]].get("sourceDays")
        days_seen[d] = days_seen.get(d, 0) + 1
    texts = sorted({str(pages[r["asin"]].get("deliveryText"))[:50] for r in live})[:4]
    buckets = {"under 5%": 0, "5-20%": 0, "over 20%": 0}
    for c in report["changes"]:
        if "price" in c and c.get("oldPrice"):
            d = abs(float(c["price"]) - c["oldPrice"]) / c["oldPrice"]
            buckets["under 5%" if d < 0.05 else "5-20%" if d < 0.2 else "over 20%"] += 1
    print("Delivery days read (None = no date):", days_seen, "| examples:", texts)
    print("Size of the price changes:", buckets)
    print(f"{report['noDeliveryDate']} pages in stock without a delivery date (stock left as is).")
    print(f"{'DRY RUN: ' if dry else ''}{prices} prices changed, {stock} stock changes, "
          f"{len(report['skipped'])} big changes held for review, {len(report['errors'])} pages not read, "
          f"{len(report['republished'])} set-aside products back online, {len(report['stillParked'])} still set aside, "
          f"{len(report['parkedNow'])} set aside now, {len(report['sellerFlags'])} non-verified sellers flagged, {errors} Shopify errors. Report: {path}")


if __name__ == "__main__":
    main()
