#!/usr/bin/env python3
"""Amazon.ae price and stock sync for a Shopify store.

Usage: python3 -I amazon_sync.py results_dir
Settings come from environment variables (GitHub Actions secrets and variables): SHOPIFY_STORE and
SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET (or SHOPIFY_TOKEN); PRICE_FORMULA (kept out of the code). Optional: DRY_RUN=1 (read and report only), LIMIT=n, SHARD=i/n, ONLY_ASINS, DELAY, FETCHER=browser (headless Chromium set to Dubai, see browser_fetch.py).
In GitHub Actions missing credentials are a failure (an alert); elsewhere the script does nothing and exits cleanly.

For every variant that has an ASIN (SKU "B0…" / "AMZ-B0…", or the product metafield when the product has one variant) it
reads the Amazon.ae page (amazon_page.py: price, stock, delivery date of every offer of the buy box, which item the page
is about) and updates the price, the "continue selling" setting and the supplier.* metafields.

What never changes a variant: a page that could not be read (blocked, partial, wrong delivery city, or not
understood because Amazon.ae changed its layout: see layout_watch). What hides it: out of
stock, too slow, a tiny stock, a listing that was removed, a page that now shows ANOTHER item (another ASIN). What never
hides it: another seller, a changed title, description or shade label on the same ASIN (Hoodo, 10 Nov).
The decisions are taken by plan(), a function without side effects that the tests run offline.
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
import urllib.error
import urllib.parse
import urllib.request
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I does not add the script folder
import amazon_page  # noqa: E402,F401  (reading of the Amazon.ae pages, tested offline)
from amazon_page import ASIN_RE, EXTRA_DAYS, MONTHS, days_until, dubai_now, dubai_today, parse, parse_price, parse_seller  # noqa: E402,F401
import suppliers  # noqa: E402  (the other sources: MedX, PadelShop.ae)

API = "2025-07"
try:  # one secret "a,b,c" holds the price formula, so masking hides it as a whole in the logs
    MARGIN_CUSTOMS, SHIPPING_AED_PER_KG, AED_TO_FDJ = (float(x) for x in os.environ.get("PRICE_FORMULA", "").split(","))
except ValueError:
    MARGIN_CUSTOMS = SHIPPING_AED_PER_KG = AED_TO_FDJ = 0.0
DEFAULT_WEIGHT_G = 200
MAX_CHANGE = 1.50  # a price that would rise by more than this share (+150 %) is held until a later reading confirms it
# Since 10 Nov: a price that would FALL by more than this share is held too (a misread price, a pack or a size that is not ours
# would sell below cost); the old price stays meanwhile. Both kinds are applied once a reading at least PRICE_CONFIRM_HOURS
# later gives the same amount (about 5 % tolerance). A held rise puts the variant to Épuisé meanwhile: its real cost is unknown.
PRICE_DROP_MAX = float(os.environ.get("PRICE_DROP_MAX", "0.4"))
PRICE_CONFIRM_HOURS = float(os.environ.get("PRICE_CONFIRM_HOURS", "3"))
# Since 10 Nov: when the only delivery offered to Dubai is a PAID standard one (e.g. AED 9), its fee is added to the Amazon.ae
# price before the formula, so the margin is not eaten. INCLUDE_DELIVERY_FEE=0 turns it off.
INCLUDE_DELIVERY_FEE = os.environ.get("INCLUDE_DELIVERY_FEE", "1") == "1"
# Delivery to Dubai (never a Rush / same-day express option) up to MAX_DAYS days is sellable, which gives the "4 to 5 days"
# shown in the shop (2 + 2-3 days of forwarding to Djibouti); anything later counts as out of stock.
# The date that counts is the one Hoodo's account gets (amazon_page.pick_delivery): for an offer shipped by Amazon itself
# the "fastest delivery" date, else the free date, else a paid standard one. MAX_DAYS can be changed without touching the code.
MAX_DAYS = int(os.environ.get("MAX_DAYS", "2"))
STANDARD_DAYS = MAX_DAYS  # up to this many days to Dubai: standard delay; later (if MAX_DAYS is raised): longer delay shown
# Since 11 Nov: every evening, once Amazon's dispatch cut-off has passed (about 20:00-21:00 in Dubai), the dates slip by one
# day until midnight, then come back. Measured on 10-11 Nov on the whole catalogue: 1,469 variants at 1 day at 19:00, none
# at 21:45 (all at 2 days); the next evening 1,700 variants went from 2 to 3 days. That is the hour the shop sells most, and
# the order check then flagged a whole order as unbuyable (order #1048; #1039 looks the same). So, from EVENING_FROM_HOUR
# (Dubai time) to midnight, a variant that is ALREADY ON SALE keeps EVENING_SLACK_DAYS more day(s). A variant that is Épuisé
# only comes back under the strict rule, at any hour: nothing slow is put on sale by this slack, and a variant that is
# really slow goes out at the first morning check. EVENING_SLACK_DAYS=0 turns it off.
EVENING_FROM_HOUR = int(os.environ.get("EVENING_FROM_HOUR", "19"))
EVENING_SLACK_DAYS = int(os.environ.get("EVENING_SLACK_DAYS", "1"))
FORWARD_DAYS = (2, 3)  # Dubai -> Djibouti
# Since 10 Nov: "Only N left in stock" with N <= LOW_STOCK_MAX is not sellable. A tiny stock usually belongs to a small
# seller shipped by Amazon; once it is gone the offer moves to a seller who delivers the next week (orders #1014, #1040:
# the robot read "tomorrow", Hoodo saw "next week" and had to buy elsewhere). LOW_STOCK_MAX=0 turns the rule off.
LOW_STOCK_MAX = int(os.environ.get("LOW_STOCK_MAX", "3"))
# Since 11 Nov: a variant that is Épuisé only comes back when Amazon.ae shows more than LOW_STOCK_BACK units (or no "Only N
# left" line at all). With a single threshold, a stock moving between 3 and 4 put the variant on sale and off again at
# every check: 130 variants changed state twice or more in 24 hours (10-11 Nov), some of them at every single check.
LOW_STOCK_BACK = int(os.environ.get("LOW_STOCK_BACK", "5"))
PRICES_ONLY = os.environ.get("PRICES_ONLY") == "1"  # update prices only: no stock, set-aside or delivery-range change
# Since 5 Nov: a page in stock with NO delivery date for the Dubai address is not sellable (it usually means Amazon.ae
# does not deliver it there; eos body butter sold out for Hoodo while the robot read "in stock"). NO_DATE_KEEPS=1 restores
# the old behaviour (leave such variants as they are).
RETRY_MAX = int(os.environ.get("RETRY_MAX", "40"))  # pages read a second time at the end of each reader
NO_DATE_KEEPS = os.environ.get("NO_DATE_KEEPS", "0") == "1"
STOCK_GUARD = float(os.environ.get("STOCK_GUARD", "0.35"))  # share of read variants that may newly go Épuisé in one run before stock changes are held
# Since 11 Nov: Amazon.ae changes its pages (often on a share of the visitors first). Every fact has a spare reading
# (amazon_page.py); a page whose featured offer cannot be understood counts as NOT READ (never "out of stock" on a guess).
# One reader raises the alert when more than LAYOUT_MAX of its pages are in that case, read through a spare reading, or
# missing a fact altogether: the shop keeps running, and the main reading is repaired before the spare one breaks too.
LAYOUT_MAX = float(os.environ.get("LAYOUT_MAX", "0.10"))
ODD_PAGES_MAX = 0.10  # more "listing removed / another item shown" pages than this share in one reader = a misread, not the truth
PARK_TAG = "livraison-lente"  # draft + this tag = set aside for slow delivery, republished by this script
OUT_TAG = "epuise-auto"  # draft + this tag = every variant Épuisé, hidden by park_soldout.py, republished when one is sellable again
# Product tag "bloque" = no variant of this product is sold, whatever Amazon.ae says; "bloque:B0XXXXXXXX" = that variant only.
# Added and removed by hand in Shopify (no code change needed). seller-hold.json is the same list kept in the repository.
BLOCK_TAG = "bloque"
SECOND_SOURCE_TAG = "source-2"  # product with a variant sold from its second source (supplier.fallback), see fallback_sync.py
HOLD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seller-hold.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

PRODUCTS_Q = """query($after:String,$q:String!){ products(first:50, after:$after, query:$q){
  pageInfo{hasNextPage endCursor}
  nodes{ id handle vendor status tags variantsCount{ count }
    ref: metafield(namespace:"internal", key:"supplier_ref"){value}
    spreadr: metafield(namespace:"global", key:"spreadr-asin"){value}
    weight: metafield(namespace:"internal", key:"weight_g"){value}
    variants(first:100){ nodes{ id title sku price inventoryPolicy
      range: metafield(namespace:"supplier", key:"delivery_range"){value}
      state: metafield(namespace:"supplier", key:"sync_state"){value}
      fallback: metafield(namespace:"supplier", key:"fallback"){value}
      inventoryItem{ measurement{ weight{ value unit } } } } } } } }"""
PRICES_M = """mutation($p:ID!,$v:[ProductVariantsBulkInput!]!){
  productVariantsBulkUpdate(productId:$p, variants:$v){ userErrors{field message} } }"""
STATUS_M = """mutation($p:ProductUpdateInput!){productUpdate(product:$p){userErrors{field message}}}"""
TAGS_ADD_M = """mutation($id:ID!,$t:[String!]!){tagsAdd(id:$id, tags:$t){userErrors{field message}}}"""
TAGS_REMOVE_M = """mutation($id:ID!,$t:[String!]!){tagsRemove(id:$id, tags:$t){userErrors{field message}}}"""
META_M = """mutation($m:[MetafieldsSetInput!]!){metafieldsSet(metafields:$m){userErrors{field message}}}"""


class LocationLost(RuntimeError):
    """The pages no longer show the Dubai delivery address: their delivery dates are worth nothing."""


def have_credentials():
    """True when the Shopify credentials are set. In GitHub Actions their absence is a failure (a deleted or renamed secret
    used to end every run "green" while nothing was checked); on a laptop the script just does nothing."""
    if os.environ.get("SHOPIFY_STORE") and (os.environ.get("SHOPIFY_TOKEN") or os.environ.get("SHOPIFY_CLIENT_SECRET")):
        return True
    if os.environ.get("GITHUB_ACTIONS") == "true":
        sys.exit("ALERTE: the Shopify secrets are missing in GitHub Actions: no control can run.")
    print("No Shopify credentials set: nothing to do.")
    return False


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
    for attempt in range(1, 31):
        req = urllib.request.Request(
            f"https://{os.environ['SHOPIFY_STORE']}/admin/api/{API}/graphql.json",
            data=json.dumps({"query": query, "variables": variables}).encode(),
            headers={"Content-Type": "application/json",
                     "X-Shopify-Access-Token": token()})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.load(r)
        except (TimeoutError, OSError, ValueError) as e:  # read timeout / connection reset / cut-off reply (5 Nov):
            if attempt >= 6:                               # every call here is safe to repeat (it sets values)
                raise
            print(f"Shopify did not answer ({type(e).__name__}), try {attempt} of 6", flush=True)
            time.sleep(10 * attempt + random.uniform(0, 5))
            continue
        throttled = any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in res.get("errors") or [])
        if throttled and attempt < 30:  # 16 shards share the store's query budget: wait for it to refill (a shard died on 2 Nov after 10 tries)
            time.sleep(min(60, 5 * attempt) + random.uniform(0, 5))
            continue
        if res.get("errors"):
            raise RuntimeError(res["errors"])
        return res["data"]


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def hours_since(text, now):
    """Hours between an ISO time and now (negative when the time is in the future); a huge number when unreadable."""
    try:
        t = dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return 1e9
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return (now - t).total_seconds() / 3600


def read_state(meta):
    """supplier.sync_state of a variant, the robot's memory between two runs:
    "pend" {aed, t} = a price jump seen at t, waiting for a second reading; "src" / "src_t" = sold from its second source,
    last confirmed at src_t; "cool" = not to be put back on sale before that time (an order just proved it unavailable);
    "why" = why the variant is Épuisé (why_out), absent when it is on sale."""
    try:
        state = json.loads((meta or {}).get("value") or "{}")
    except ValueError:
        return {}
    return state if isinstance(state, dict) else {}


def load_hold_list():
    """ASINs of seller-hold.json. A broken file stops the run (it used to crash every reader AFTER the reading)."""
    if not os.path.exists(HOLD_FILE):
        return set()
    try:
        asins = json.load(open(HOLD_FILE)).get("asins", [])
        bad = [a for a in asins if not (isinstance(a, str) and ASIN_RE.fullmatch(a))]
    except (ValueError, AttributeError) as e:
        sys.exit(f"ALERTE: seller-hold.json cannot be read ({e}): nothing changed.")
    if bad:
        sys.exit(f"ALERTE: seller-hold.json holds entries that are not ASINs ({bad[:5]}): nothing changed.")
    return set(asins)


def load_variants(held=()):
    rows = []
    for search, parked in (("status:active", False),
                           (f"status:draft (tag:{PARK_TAG} OR tag:{OUT_TAG})", True)):
        rows += load_rows(search, parked, held)
    return rows


def load_rows(search, parked, held=()):
    rows, after = [], None
    while True:
        data = gql(PRODUCTS_Q, {"after": after, "q": search})["products"]
        for p in data["nodes"]:
            total = ((p.get("variantsCount") or {}).get("count")) or len(p["variants"]["nodes"])
            if total > len(p["variants"]["nodes"]):
                print(f"::warning::{p['handle']} has {total} variants, only the first {len(p['variants']['nodes'])} are checked")
            tags = {t.lower() for t in p.get("tags") or []}
            product_asin = None
            for src in (p.get("spreadr"), p.get("ref")):
                m = src and ASIN_RE.search(src["value"])
                if m:
                    product_asin = m.group(1)
                    break
            for v in p["variants"]["nodes"]:
                if suppliers.is_other_source(v.get("sku")):
                    continue  # MEDX- / PSAE- variants are read by their own sync
                m = ASIN_RE.search(v.get("sku") or "")
                asin = m.group(1) if m else (product_asin if total == 1 else None)
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
                             "variantId": v["id"], "variant": v["title"], "asin": asin, "price": float(v["price"]),
                             "policy": v["inventoryPolicy"], "policy0": v["inventoryPolicy"],
                             "grams": grams or DEFAULT_WEIGHT_G, "range": (v.get("range") or {}).get("value"),
                             "state": read_state(v.get("state")),
                             "fallback": ((v.get("fallback") or {}).get("value") or "").strip(),
                             "blocked": BLOCK_TAG in tags or f"{BLOCK_TAG}:{asin.lower()}" in tags or asin in held,
                             "parked": parked, "nvariants": total})
        if not data["pageInfo"]["hasNextPage"]:
            return rows
        after = data["pageInfo"]["endCursor"]


READER = None  # set to a browser_fetch.BrowserReader when FETCHER=browser


def fetch(asin):
    url = f"https://www.amazon.ae/dp/{asin}?language=en_AE"
    if READER:
        return READER.get(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-AE,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:  # a removed listing: its body says so (amazon_page.gone_page)
            return e.read().decode("utf-8", "replace")
        raise


def read_page(asin):
    """The page of an ASIN, with the offer to buy chosen (choose_offer). A page that shows another delivery city is not
    used: the Dubai address is set again once, and the reading stops (LocationLost) if it still does not hold."""
    page = parse(fetch(asin), dubai_today(), asin)
    if page.get("error") == "location":
        if READER:
            READER.set_location()
            page = parse(fetch(asin), dubai_today(), asin)
        if page.get("error") == "location":
            raise LocationLost(f"delivery location is '{page.get('location')}', not {amazon_page.CITY}")
    if not page.get("error"):
        page["hour"] = dubai_now().hour  # the hour of the reading decides the evening slack (days_allowed)
    return choose_offer(page)


def low_stock(page, on_sale=True):
    """Only a few units left on Amazon.ae: the offer can switch to a slow seller at any moment. A variant on sale goes
    out at LOW_STOCK_MAX units or fewer; one that is Épuisé needs more than LOW_STOCK_BACK to come back."""
    left = page.get("stockLeft")
    limit = LOW_STOCK_MAX if on_sale else max(LOW_STOCK_MAX, LOW_STOCK_BACK)
    return LOW_STOCK_MAX > 0 and left is not None and left <= limit


def days_allowed(on_sale, hour):
    """Days to Dubai accepted for a variant: MAX_DAYS, plus the evening slack when the variant is already on sale and the
    page was read between EVENING_FROM_HOUR and midnight in Dubai (hour None = unknown: strict)."""
    late = on_sale and hour is not None and hour >= EVENING_FROM_HOUR
    return MAX_DAYS + (EVENING_SLACK_DAYS if late else 0)


def sellable(page, max_days=None, on_sale=True):
    """Can this offer be bought now and reach Dubai in time (max_days, by default the strict MAX_DAYS)? on_sale=False
    asks more stock of a variant that is Épuisé before it comes back. The seller's name plays no part."""
    if page.get("error") or page.get("held") or page.get("gone") or page.get("redirect"):
        return False
    if low_stock(page, on_sale):
        return False
    days = page.get("sourceDays")
    return bool(page.get("inStock")) and days is not None and days <= (MAX_DAYS if max_days is None else max_days)


def choose_offer(page, max_days=None, on_sale=True):
    """Some buy boxes list several offers (two sellers, each with its price, stock and date). The first one that can be
    sold is the one we would buy; without any, the featured offer describes the page."""
    if page.get("error") or page.get("gone") or page.get("redirect"):
        return page
    offers = page.get("offers") or []
    for k, offer in enumerate(offers):
        chosen = {**page, **offer, "offer": k}
        if sellable(chosen, max_days, on_sale):
            return chosen
    return {**page, **offers[0], "offer": 0} if offers else page


def offer_for(page, on_sale):
    """(the offer we would buy, can it be sold?) for a variant that is on sale or not: a variant on sale gets the evening
    slack, one that is Épuisé must meet the strict rule to come back. An offer inside the strict rule is always preferred."""
    page = choose_offer(page, None, on_sale)
    if sellable(page, None, on_sale):
        return page, True
    limit = days_allowed(on_sale, page.get("hour"))
    if limit > MAX_DAYS:
        page = choose_offer(page, limit, on_sale)
    return page, sellable(page, limit, on_sale)


def why_out(page, on_sale=True, blocked=False, cooling=False, hold=None):
    """Why a variant is Épuisé, as a short code kept on the variant (supplier.sync_state "why") and counted in the
    reports and in the audit, so "why are so many products hidden?" has an answer at every check:
    retenue (held by hand), pause-commande (an order just proved it unavailable), prix (price jump waiting for a second
    reading), fiche-supprimee, autre-article, rupture, amazon-now (only the Amazon Now box is offered, no ordinary
    offer), stock-bas, sans-date (no delivery date for Dubai: mostly Amazon US / UK imports), delai:3 (one day too slow)
    or delai:4+."""
    if blocked:
        return "retenue"
    if cooling:
        return "pause-commande"
    if hold == "rise":
        return "prix"
    if page.get("gone"):
        return "fiche-supprimee"
    if page.get("redirect"):
        return "autre-article"
    if not page.get("inStock"):
        return "amazon-now" if page.get("amazonNow") else "rupture"
    if low_stock(page, on_sale):
        return "stock-bas"
    if page.get("sourceDays") is None:
        return "sans-date"
    return "delai:3" if page["sourceDays"] <= MAX_DAYS + 1 else "delai:4+"


def cost_of(page):
    """What the item costs us in Dubai: its price, plus the delivery fee when no free delivery exists."""
    fee = page.get("deliveryFee") or 0.0
    return page["aed"] + (fee if INCLUDE_DELIVERY_FEE else 0.0)


def formula(aed, grams):
    fdj = (aed * MARGIN_CUSTOMS + grams / 1000 * SHIPPING_AED_PER_KG) * AED_TO_FDJ
    return int(math.ceil(fdj / 50) * 50)


def guard_price(old, new, aed, state, now):
    """(price to set or None, "rise" / "drop" when the change is held, new state).
    A jump beyond the limits is not applied at once: the amount and the time are remembered ("pend") and the change goes
    through when a reading at least PRICE_CONFIRM_HOURS later gives the same amount. Normal changes clear the memory."""
    rest = {k: v for k, v in state.items() if k != "pend"}
    if not old or old <= 0:
        return new, None, rest
    kind = "rise" if new > old * (1 + MAX_CHANGE) else "drop" if new < old * (1 - PRICE_DROP_MAX) else None
    if not kind:
        return new, None, rest
    pend = state.get("pend") if isinstance(state.get("pend"), dict) else {}
    same = bool(pend.get("aed")) and abs(pend["aed"] - aed) <= 0.05 * aed
    if same and hours_since(pend.get("t"), now) >= PRICE_CONFIRM_HOURS:
        return new, None, rest
    if same:
        return None, kind, dict(state)
    return None, kind, {**rest, "pend": {"aed": round(aed, 2), "t": iso(now)}}


def no_date(page):
    """In stock without a delivery date, in the old "leave it as it is" mode (NO_DATE_KEEPS=1)."""
    return NO_DATE_KEEPS and bool(page.get("inStock")) and page.get("sourceDays") is None and not page.get("held")


def plain(text):
    """Lower case, accents removed (L'Oréal -> l'oreal)."""
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().strip().lower()


def seller_class(seller, vendor):
    """amazon / brand / third_party, or unknown when the page gave no seller name. For information only."""
    s = plain(seller)
    if not s:
        return "unknown"
    if "amazon" in s:
        return "amazon"
    tokens = [w for w in re.findall(r"[a-z0-9]+", plain(vendor)) if len(w) > 2]
    return "brand" if tokens and tokens[0] in s else "third_party"


def same_name(variant, variation):
    """True when the option shown by Amazon.ae and our variant name share their words (report only, never hides)."""
    a, b = (set(re.findall(r"[a-z0-9]+", plain(x))) for x in (variant, variation))
    return not a or not b or a <= b or b <= a or variant == "Default Title"


def eta_of(days):
    """Delivery in Djibouti as "a-b" days: days to Dubai + 2 to 3 days of forwarding."""
    return f"{days + FORWARD_DAYS[0]}-{days + FORWARD_DAYS[1]}"


def delivery_eta(page):
    return eta_of(page["sourceDays"])


def delivery_range(page):
    days = page.get("sourceDays")
    return "standard" if days is not None and days <= STANDARD_DAYS else "3-10"


HIDE_EVERY = 50  # pages between two "hide what is unavailable now" passes


def hide_unavailable(rows, pages, dry, hidden):
    """Épuisé straight away for the variants whose page, read so far, says they cannot be bought, instead of waiting
    for the end of the run. Only ever hides (prices and put-back-on-sale wait for the end). Not hidden here: a variant
    with a second source (the end of the run decides), a page in stock without a date (often a page that did not finish
    loading: it is read again first). The guard counts everything hidden since the start of the run, so a reading that
    goes wrong slowly cannot empty the shop 50 pages at a time. hidden = ids of the variants hidden so far (updated)."""
    if dry or PRICES_ONLY:
        return
    live = [r for r in rows if not r["parked"] and pages.get(r["asin"]) and not pages[r["asin"]].get("error")]
    out = [r for r in live if r["policy"] == "CONTINUE" and not r["fallback"]
           and not (pages[r["asin"]].get("inStock") and pages[r["asin"]].get("sourceDays") is None)
           and not offer_for(pages[r["asin"]], True)[1]]
    if len(live) < 20 or len(hidden) + len(out) > STOCK_GUARD * len(live):
        return
    by_product = {}
    for r in out:
        by_product.setdefault(r["productId"], []).append(r)
    done = 0
    for pid, mine in by_product.items():
        errs = gql(PRICES_M, {"p": pid, "v": [{"id": r["variantId"], "inventoryPolicy": "DENY"} for r in mine]}
                   )["productVariantsBulkUpdate"]["userErrors"]
        if errs:
            print("hide error:", pid, errs)
            continue
        for r in mine:
            r["policy"] = "DENY"
            hidden.add(r["variantId"])
            done += 1
    if done:
        print(f"{done} variants set to Épuisé right away ({time.strftime('%H:%M:%S')})", flush=True)


def plan(rows, pages, now, fetch_other=None, hidden=(), prices_only=False):
    """What to do with every variant whose page was read. No side effect: (decisions, info).
    A decision = {"r": row, "page", "sell", "src" ("amazon" or the second-source reference), "cost" (AED), "days" (to
    Dubai), "policy", "price" (to set, or None), "hold" ("rise"/"drop": price jump waiting for a confirmation), "state",
    "applied" (False = nothing is written for this variant: stock guard, prices-only run, page without a date in the old
    mode, second source that could not be read)}. fetch_other(module, slug) reads a second source (None = never)."""
    hidden, others, decisions = set(hidden), {}, []
    for r in rows:
        page = pages.get(r["asin"])
        if not page or page.get("error"):
            continue
        state = dict(r["state"])
        cooling = bool(state.get("cool")) and hours_since(state["cool"], now) < 0
        if state.get("cool") and not cooling:
            state.pop("cool")
        # on sale when the run started (policy0: hide_unavailable may have set "policy" to DENY during this very run)
        on_sale = r["policy0"] == "CONTINUE" and not r["parked"]
        page, can_sell = offer_for(page, on_sale)
        d = {"r": r, "page": page, "sell": False, "src": "amazon", "cost": None, "days": None, "price": None,
             "hold": None, "wait": False, "why": None}
        if r["blocked"] or cooling:
            pass
        elif can_sell:  # days: never more than MAX_DAYS for the shop's delivery label, also under the evening slack
            d.update(sell=True, cost=cost_of(page), days=min(page["sourceDays"], MAX_DAYS))
        elif r["fallback"] and fetch_other:
            mod, slug, _ = suppliers.module_of(r["fallback"])
            if mod:
                if (mod, slug) not in others:
                    others[(mod, slug)] = fetch_other(mod, slug)
                other = others[(mod, slug)]
                using = r["policy"] == "CONTINUE" and state.get("src") == r["fallback"]
                if other.get("error"):
                    d["wait"] = using  # sold from it and unreadable right now: fallback_sync.py decides, not this run
                elif mod.sellable(other, using):
                    d.update(sell=True, src=r["fallback"], cost=other["aed"], days=mod.DUBAI_DAYS)
        if d["sell"]:
            new = formula(d["cost"], r["grams"])
            if r["parked"] or abs(new - r["price"]) >= 50:  # a republished product always gets a fresh price
                d["price"], d["hold"], state = guard_price(r["price"], new, d["cost"], state, now)
            else:
                state.pop("pend", None)
            if d["hold"] == "rise":  # the real cost is unknown until the second reading: not sold meanwhile
                d["sell"] = False
        if d["sell"] and d["src"] != "amazon":
            state["src"], state["src_t"] = d["src"], iso(now)
        else:
            state.pop("src", None)
            state.pop("src_t", None)
        if d["sell"]:
            state.pop("why", None)
        else:
            d["why"] = state["why"] = why_out(page, on_sale, r["blocked"], cooling, d["hold"])
        d["policy"], d["state"] = ("CONTINUE" if d["sell"] else "DENY"), state
        decisions.append(d)
    # Safety net: if too many variants would newly go Épuisé in one run (counting those already hidden during the
    # reading), the page reading is probably off (wrong location, blocking): nothing is written for this reader, not even
    # the "verified" stamp, so the coverage check reads these variants again and hides what stays unverified.
    live = [d for d in decisions if not d["r"]["parked"]]
    newly_out = [d for d in live if (d["r"]["policy"] == "CONTINUE" or d["r"]["variantId"] in hidden)
                 and not d["sell"] and not d["r"]["blocked"] and not no_date(d["page"])]
    guard = len(live) >= 20 and len(newly_out) > STOCK_GUARD * len(live)
    for d in decisions:
        d["applied"] = not (prices_only or guard or d["wait"] or no_date(d["page"]))
        if prices_only:  # prices only: the stock setting stays, a price is set only on what is on sale and sellable
            if not (d["sell"] and d["r"]["policy"] == "CONTINUE"):
                d["price"] = None
            d["policy"] = d["r"]["policy"]
    revive = {d["r"]["productId"] for d in decisions if d["r"]["parked"] and d["applied"] and d["policy"] == "CONTINUE"}
    return decisions, {"guard": guard, "live": len(live), "newlyOut": len(newly_out), "revive": revive}


def read_all(asins, rows, dry, hidden, delay):
    """Reads the pages one by one, slowly. Returns (pages, why the reading stopped early or None)."""
    pages, blocked, stopped = {}, 0, None
    for n, asin in enumerate(asins, 1):
        try:
            pages[asin] = read_page(asin)
        except Exception as e:  # network error, browser error
            if type(e).__name__ == "LocationLost":
                stopped = f"{e}: stopped after {n - 1} of {len(asins)} pages, the rest is left unchanged"
                break
            pages[asin] = {"error": str(e)[:100] or type(e).__name__}
        blocked = blocked + 1 if pages[asin].get("error") == "captcha" else 0
        if blocked:  # Amazon asked for a CAPTCHA: back off for a while instead of insisting
            time.sleep(60 + random.uniform(0, 60))
        if blocked >= 5:
            stopped = f"Amazon.ae is showing CAPTCHAs: stopped after {n} of {len(asins)} pages, the rest is left unchanged"
            break
        if n % HIDE_EVERY == 0:
            hide_unavailable(rows, pages, dry, hidden)
        if n % 25 == 0:
            bad = sum(1 for p in pages.values() if p.get("error"))
            print(f"{n}/{len(asins)} pages read, {bad} not read ({time.strftime('%H:%M:%S')})", flush=True)
        time.sleep(delay + random.uniform(0, delay / 2))

    # Second chance, slowly, for the pages not read (error, CAPTCHA), read in stock without a delivery date (often a page
    # that did not finish loading) or read as removed / replaced (a serious verdict: it is checked twice).
    def unclear(p):
        return p.get("error") or p.get("gone") or p.get("redirect") or (p.get("inStock") and p.get("sourceDays") is None)

    if not stopped:
        again = [a for a, p in pages.items() if unclear(p)][:RETRY_MAX]
        if again:
            print(f"Reading {len(again)} pages again (not read, no delivery date, removed or replaced)", flush=True)
        fixed, blocked = 0, 0
        for asin in again:
            time.sleep(2 * delay + random.uniform(0, delay))
            try:
                pg = read_page(asin)
            except Exception as e:
                if type(e).__name__ == "LocationLost":
                    stopped = f"{e}: stopped during the second reading"
                    break
                continue
            if pg.get("error") == "captcha":
                blocked += 1
                if blocked >= 3:
                    break
                time.sleep(60 + random.uniform(0, 60))
                continue
            blocked = 0
            if not pg.get("error") and (not unclear(pg) or pages[asin].get("error")
                                        or (pages[asin].get("inStock") and not pg.get("inStock"))):
                pages[asin] = pg
                fixed += 1
        if again:
            print(f"Second read: {fixed} of {len(again)} pages now read with a clear answer", flush=True)
    # Many "removed" or "another item" pages at once is how a block or a broken layout looks, not what Amazon.ae sells.
    odd = [a for a, p in pages.items() if p.get("gone") or p.get("redirect")]
    readable = sum(1 for p in pages.values() if not p.get("error"))
    if len(odd) > max(5, ODD_PAGES_MAX * readable):
        print(f"::warning::{len(odd)} of {readable} pages read as removed or replaced: taken as a misread, left unchanged")
        for a in odd:
            pages[a] = {"error": "removed/replaced pages in bulk (misread?)"}
    return pages, stopped


FACT_NAMES = {"price": "the price", "delivery": "the delivery date", "stock": "the stock line", "cart": "the add-to-cart "
              "button", "shipper": "who ships the offer", "buybox": "the buy box", "title": "the product title",
              "location": "the delivery city", "offer": "the offer"}


def layout_watch(pages):
    """What this reading says about the layout of Amazon.ae's pages: (stats for the report, alert lines).
    Changes pages in one case: far more pages "in stock without a delivery date" than Amazon.ae ever has (2 to 4 % are
    imports without a date) is a delivery block that changed, not the truth: those pages become NOT READ."""
    stats = {"unreadable": {}, "spare": {}, "missing": {}, "noDateInBulk": 0,
             "amazonNow": sum(1 for p in pages.values() if p.get("amazonNow"))}
    for p in pages.values():
        if p.get("layout"):
            stats["unreadable"][p["layout"]] = stats["unreadable"].get(p["layout"], 0) + 1
        if p.get("error"):
            continue
        for k in set((p.get("via") or []) + (p.get("pageVia") or [])):
            stats["spare"][k] = stats["spare"].get(k, 0) + 1
        for k in set((p.get("blind") or []) + (p.get("pageBlind") or [])):
            stats["missing"][k] = stats["missing"].get(k, 0) + 1
    readable = sum(1 for p in pages.values() if not p.get("error"))
    alerts = []
    no_date = [a for a, p in pages.items() if not p.get("error") and p.get("inStock") and p.get("sourceDays") is None
               and not p.get("held")]
    if len(no_date) > max(8, LAYOUT_MAX * readable):
        stats["noDateInBulk"] = len(no_date)
        for a in no_date:
            pages[a] = {"error": "layout: delivery", "layout": "delivery"}
        alerts.append(f"{len(no_date)} of {readable} pages in stock show no delivery date (2 to 4 % is normal): Amazon.ae "
                      "probably changed its delivery block. These pages count as not read, nothing was hidden for it.")
        readable -= len(no_date)
    unreadable = sum(stats["unreadable"].values())
    if unreadable > max(5, LAYOUT_MAX / 2 * len(pages)):
        what = ", ".join(f"{FACT_NAMES.get(k, k)} ({n})" for k, n in sorted(stats["unreadable"].items(), key=lambda x: -x[1]))
        alerts.append(f"{unreadable} of {len(pages)} pages could not be understood, missing: {what}. Amazon.ae probably "
                      "changed its page. These pages count as not read: nothing hidden on a guess, nothing confirmed.")
    for kind, text in (("spare", "read only through the spare reading: the shop still works, repair the main reading"),
                       ("missing", "not found at all: a rule is off for these pages (low stock, fastest date or city check)")):
        for k, n in sorted(stats[kind].items(), key=lambda x: -x[1]):
            if n >= max(10, LAYOUT_MAX * readable):
                alerts.append(f"{FACT_NAMES.get(k, k)} was {text} ({n} of {readable} pages).")
    return stats, alerts


def start_browser():
    """A headless browser set to the Dubai address: up to 3 tries, whatever goes wrong (address, CAPTCHA, a crash)."""
    global READER
    import browser_fetch
    for attempt in range(1, 4):
        reader = browser_fetch.BrowserReader()
        try:
            READER = reader.start()
            break
        except Exception as e:
            try:
                reader.close()
            except Exception:
                pass
            if attempt == 3:
                sys.exit(f"ALERTE: the browser could not start on Amazon.ae with a Dubai address ({type(e).__name__}: "
                         f"{str(e)[:120]}), 3 tries: nothing changed.")
            print(f"Browser not ready ({type(e).__name__}: {str(e)[:120]}), try {attempt} of 3: again in a minute", flush=True)
            time.sleep(45 + random.uniform(0, 30))
    print("Browser reader started, delivery location:", READER.location_text())


def field(owner, key, kind, value, namespace="supplier"):
    return {"ownerId": owner, "namespace": namespace, "key": key, "type": kind, "value": value}


def main():
    if not have_credentials():
        return
    if not (MARGIN_CUSTOMS and SHIPPING_AED_PER_KG and AED_TO_FDJ):
        sys.exit("ALERTE: PRICE_FORMULA secret is missing or malformed: nothing changed.")
    outdir = sys.argv[1] if len(sys.argv) > 1 else "results"
    os.makedirs(outdir, exist_ok=True)
    dry = os.environ.get("DRY_RUN") == "1"
    delay = float(os.environ.get("DELAY", "8"))
    now_t = dt.datetime.now(dt.timezone.utc)
    now = iso(now_t)
    held = load_hold_list()
    rows = load_variants(held)
    by_asin = {}
    for r in rows:
        by_asin.setdefault(r["asin"], []).append(r)
    asins = sorted(by_asin)
    if os.environ.get("LIMIT"):
        n_max = int(os.environ["LIMIT"])  # an evenly spread sample, not just the first ASINs
        asins = asins[::max(1, len(asins) // n_max)][:n_max]
    if os.environ.get("ONLY_ASINS"):  # a retry pass: only these ASINs (comma-separated), see coverage.py
        wanted = set(os.environ["ONLY_ASINS"].split(","))
        asins = [a for a in asins if a in wanted]
    if os.environ.get("SHARD"):  # "i/n": a stable share of the ASINs, so adding a product does not reshuffle the readers
        i, n = (int(x) for x in os.environ["SHARD"].split("/"))
        asins = [a for a in asins if zlib.crc32(a.encode()) % n == i]
    # Blocked variants (tag "bloque", seller-hold.json): Épuisé first, before any reading, and their page is not read.
    skip = {a for a in asins if all(r["blocked"] for r in by_asin[a])}
    block_now = [r for a in skip for r in by_asin[a] if r["policy"] == "CONTINUE"]
    if block_now and not dry and not PRICES_ONLY:
        for r in block_now:
            errs = gql(PRICES_M, {"p": r["productId"], "v": [{"id": r["variantId"], "inventoryPolicy": "DENY"}]}
                       )["productVariantsBulkUpdate"]["userErrors"]
            if errs:
                print("block error:", r["handle"], errs)
            else:
                r["policy"] = "DENY"
    asins = [a for a in asins if a not in skip]
    print(f"{len(rows)} variants with an ASIN, {len(asins)} Amazon pages to read, {len(skip)} blocked by hand "
          f"({len(block_now)} of them were on sale)")
    if os.environ.get("FETCHER") == "browser":  # real headless browser set to a Dubai delivery address
        start_browser()
    if os.environ.get("SHARD"):  # parallel readers do not all start at the same second
        time.sleep(random.uniform(0, 60))
    hidden = set()
    try:
        pages, stopped = read_all(asins, rows, dry, hidden, delay)
    finally:
        if READER:
            READER.close()

    layout, layout_alerts = layout_watch(pages)
    decisions, info = plan(rows, pages, now_t, fetch_other=lambda mod, slug: mod.fetch(slug), hidden=hidden,
                           prices_only=PRICES_ONLY)
    revive = info["revive"]
    report = {"checkedAt": now, "dryRun": dry, "shard": os.environ.get("SHARD"), "pagesAsked": len(asins),
              "pagesRead": sum(1 for p in pages.values() if not p.get("error")), "changes": [], "skipped": [],
              "errors": [], "republished": [], "stillParked": [], "gone": [], "redirected": [], "secondSource": [],
              "nameMismatch": [], "blocked": len(skip), "hiddenDuringRun": len(hidden),
              "stockGuardTripped": info["guard"], "stoppedEarly": stopped, "layout": layout,
              "layoutAlerts": layout_alerts}
    for r in rows:
        page = pages.get(r["asin"])
        if page and page.get("error"):
            report["errors"].append({"asin": r["asin"], "handle": r["handle"], "error": page["error"]})
    if info["guard"]:
        print(f"Stock guard: {info['newlyOut']} of {info['live']} variants would newly go Épuisé, no stock change made.")
    by_product, stamps, agg, second = {}, {}, {}, set()
    for d in decisions:
        r, page = d["r"], d["page"]
        who = {"handle": r["handle"], "variant": r["variant"], "asin": r["asin"]}
        if page.get("gone"):
            report["gone"].append(who)
        if page.get("redirect"):
            report["redirected"].append({**who, "shows": page["redirect"]})
        if page.get("variation") and r["nvariants"] > 1 and not same_name(r["variant"], page["variation"]):
            report["nameMismatch"].append({**who, "amazon": page["variation"]})
        if r["parked"] and r["productId"] not in revive:
            report["stillParked"].append({**who, "aed": page.get("aed"), "inStock": page.get("inStock"),
                                          "delivery": page.get("deliveryText"), "days": page.get("sourceDays")})
        if d["hold"]:
            report["skipped"].append({**who, "aed": d["cost"], "now": r["price"], "formula": formula(d["cost"], r["grams"]),
                                      "kind": d["hold"]})
        upd = {"id": r["variantId"]}
        if d["price"] is not None and (d["applied"] or PRICES_ONLY):
            upd["price"] = str(d["price"])
        if d["applied"]:
            # DENY is sent even when the variant already looked Épuisé: another run may have put it back meanwhile
            if d["policy"] != r["policy"] or d["policy"] == "DENY":
                upd["inventoryPolicy"] = d["policy"]
            mine = stamps.setdefault(r["productId"], [])
            mine.append(field(r["variantId"], "variant_checked_at", "date_time", now))  # coverage.py checks it
            if d["state"] != r["state"]:
                mine.append(field(r["variantId"], "sync_state", "json", json.dumps(d["state"], separators=(",", ":"))))
            if d["policy"] == "CONTINUE":
                mine.append(field(r["variantId"], "delivery_eta", "single_line_text_field", eta_of(d["days"])))
                rng = "standard" if d["days"] <= STANDARD_DAYS else "3-10"
                if rng != r["range"]:
                    mine.append(field(r["variantId"], "delivery_range", "single_line_text_field", rng))
                if d["src"] != "amazon":
                    second.add(r["productId"])
                    report["secondSource"].append({**who, "source": d["src"], "aed": d["cost"]})
            agg.setdefault(r["productId"], []).append(d)
        changed = {k: v for k, v in upd.items() if k == "price" or (k == "inventoryPolicy" and v != r["policy0"])}
        if changed:
            report["changes"].append({**who, "aed": d["cost"] if d["cost"] is not None else page.get("aed"),
                                      "oldPrice": r["price"], **changed})
        if len(upd) > 1:
            by_product.setdefault(r["productId"], []).append(upd)

    errors, failed = 0, set()
    if not dry:
        for pid, ups in by_product.items():
            res = gql(PRICES_M, {"p": pid, "v": ups})["productVariantsBulkUpdate"]["userErrors"]
            if res:  # nothing of this product was written: it must not be stamped "verified"
                failed.add(pid)
                errors += len(res)
                print("price/stock error:", pid, res)
        fields = [f for pid, fs in stamps.items() if pid not in failed for f in fs]
        for pid, ds in agg.items():
            if pid in failed:
                continue
            ok = [d for d in ds if d["policy"] == "CONTINUE"]
            fields.append(field(pid, "in_stock", "boolean", "true" if ok else "false"))
            fields.append(field(pid, "checked_at", "date_time", now))
            seen = next((d["page"] for d in ds if d["page"].get("seller")), None)
            if seen:
                fields.append(field(pid, "seller", "single_line_text_field", seen["seller"][:100]))
                fields.append(field(pid, "seller_class", "single_line_text_field",
                                    seller_class(seen["seller"], ds[0]["r"]["vendor"])))
            if ok:
                fields.append(field(pid, "delivery_days", "number_integer", str(min(d["days"] for d in ok) + EXTRA_DAYS)))
        for pid in revive - failed:  # back online: ACTIVE, tag removed (after the prices and stock above)
            for q, vars_ in ((STATUS_M, {"p": {"id": pid, "status": "ACTIVE"}}),
                             (TAGS_REMOVE_M, {"id": pid, "t": [PARK_TAG, OUT_TAG]})):
                errs = next(iter(gql(q, vars_).values()))["userErrors"]
                errors += len(errs)
                for e in errs:
                    print("republish error:", pid, e)
        for pid in second - failed:
            errors += len(gql(TAGS_ADD_M, {"id": pid, "t": [SECOND_SOURCE_TAG]})["tagsAdd"]["userErrors"])
        for i in range(0, len(fields), 25):
            res = gql(META_M, {"m": fields[i:i + 25]})["metafieldsSet"]["userErrors"]
            errors += len(res)
            for e in res[:3]:
                print("metafield error:", e)

    report["republished"] = sorted({r["handle"] for r in rows if r["productId"] in revive - failed})
    report["noDeliveryDate"] = sum(1 for d in decisions if not d["r"]["parked"] and d["page"].get("inStock")
                                   and d["page"].get("sourceDays") is None)
    report["lowStock"] = sum(1 for d in decisions if not d["r"]["parked"] and low_stock(d["page"]))
    # every Épuisé variant with its reason and what the page showed: the next fine-tuning starts from facts
    report["out"] = [{"asin": d["r"]["asin"], "handle": d["r"]["handle"], "why": d["why"], "wasOnSale": d["r"]["policy0"] == "CONTINUE",
                      "days": d["page"].get("sourceDays"), "left": d["page"].get("stockLeft"),
                      "amazonShips": d["page"].get("amazonShips"), "promises": d["page"].get("promises"),
                      "hour": d["page"].get("hour")} for d in decisions if not d["sell"]]
    why_count = {}
    for d in decisions:
        if not d["sell"]:
            why_count[d["why"]] = why_count.get(d["why"], 0) + 1
    report["outByReason"] = why_count
    report["eveningSlack"] = sum(1 for d in decisions if d["sell"] and d["src"] == "amazon"
                                 and (d["page"].get("sourceDays") or 0) > MAX_DAYS)
    tail = (os.environ.get("SHARD") or "all").replace("/", "of")
    path = os.path.join(outdir, f"sync-{now[:13].replace(':', '')}-{tail}.json")
    json.dump(report, open(path, "w"), indent=1, ensure_ascii=False)

    reasons, days_seen = {}, {}
    for e in report["errors"]:
        reasons[str(e["error"])[:40]] = reasons.get(str(e["error"])[:40], 0) + 1
    for d in decisions:
        if not d["r"]["parked"]:
            days_seen[d["page"].get("sourceDays")] = days_seen.get(d["page"].get("sourceDays"), 0) + 1
    prices = sum("price" in c for c in report["changes"])
    to_out = sum(c.get("inventoryPolicy") == "DENY" for c in report["changes"])
    back = sum(c.get("inventoryPolicy") == "CONTINUE" for c in report["changes"])
    lines = [
        f"{'DRY RUN: ' if dry else ''}{report['pagesRead']} of {len(asins)} pages read, {len(report['errors'])} variants "
        f"whose page was not read" + (f" ({reasons})" if reasons else ""),
        f"Stock: {to_out} to Épuisé ({len(hidden)} of them during the reading), {back} back on sale, "
        f"{len(report['republished'])} hidden products back online, {len(report['stillParked'])} variants still hidden.",
        f"Prices: {prices} changed, {len(report['skipped'])} jumps held until a second reading.",
        f"Delivery days read (None = no date): {days_seen}",
        f"Épuisé by reason: {dict(sorted(why_count.items(), key=lambda x: -x[1]))}; {report['eveningSlack']} kept on sale "
        f"by the evening slack.",
        f"{report['noDeliveryDate']} in stock without a delivery date, {report['lowStock']} with {LOW_STOCK_MAX} or fewer "
        f"left, {len(report['gone'])} listings removed, {len(report['redirected'])} pages showing another item, "
        f"{len(report['secondSource'])} sold from their second source, {len(report['nameMismatch'])} option names that differ "
        f"(information only).",
        f"Page layout: {sum(layout['unreadable'].values())} pages not understood {layout['unreadable'] or ''}, spare "
        f"readings used {layout['spare'] or 'on no page'}, facts missing {layout['missing'] or 'on no page'}; "
        f"{layout['amazonNow']} pages offered only through Amazon Now (not sold, reason amazon-now).",
        f"{errors} Shopify errors. Report: {path}"]
    if stopped:
        lines.insert(0, f"::warning::{stopped}")
    for a in layout_alerts:
        lines.insert(0, f"::warning::Amazon.ae page layout: {a}")
    print("\n".join(lines))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(f"**Reader {tail}**\n\n" + "\n".join("- " + x.replace("::warning::", "⚠️ ") for x in lines) + "\n\n")
    # A reading that stopped early is not a failure of this reader: the coverage check reads the rest again and judges.
    if info["guard"] and not dry:
        sys.exit("ALERTE: stock guard tripped, no stock change made by this reader (probably a misread).")
    if errors and not dry:
        sys.exit(f"ALERTE: {errors} Shopify errors.")
    if layout_alerts and not dry:
        sys.exit("ALERTE: Amazon.ae page layout: " + " | ".join(layout_alerts))


if __name__ == "__main__":
    main()
