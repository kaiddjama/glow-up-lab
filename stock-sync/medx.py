#!/usr/bin/env python3
"""MedX Pharmacy (medxpharmacy.com, Dubai) as a second supplier: reads one product page.

A MedX variant is recognised by its SKU "MEDX-<product alias>" (the alias is the last part of
https://www.medxpharmacy.com/product/<alias>/). The page is public and carries the exact stock figure of the
pharmacy ("quantity"), the price in AED (VAT included) and whether the product is published. MedX delivers inside Dubai
in 12 to 24 hours, so the Dubai leg is always 1 day (well inside MAX_DAYS) and the shop label stays "4 à 5 jours".

Safety rules (lesson of orders #1014 / #1019 / #1040: never sell what is not confirmed in stock):
  - a variant is sellable only if the page was read, is published, and its stock is at least MEDX_MIN_QTY
    (8 by default); a variant that is already Épuisé only comes back when the stock reaches MEDX_BACK_QTY (12),
    so a stock that hovers around the limit does not flip the variant on and off;
  - a page that cannot be read (network, block, unexpected layout) never changes anything; coverage.py then sets
    the variant to Épuisé when it has not been read for MEDX_STALE_HOURS hours;
  - a page that no longer exists (404) means the product was removed: not sellable.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

BASE = "https://www.medxpharmacy.com"
SKU_RE = re.compile(r"^MEDX-([a-z0-9][a-z0-9-]*)$")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
MIN_QTY = int(os.environ.get("MEDX_MIN_QTY", "8"))  # below this stock the variant is Épuisé
BACK_QTY = int(os.environ.get("MEDX_BACK_QTY", "12"))  # an Épuisé variant needs this stock to come back
STALE_HOURS = int(os.environ.get("MEDX_STALE_HOURS", "1"))  # coverage.py: unread for this long = Épuisé
DUBAI_DAYS = 1  # MedX delivers in Dubai within 12 to 24 hours
FORWARD_DAYS = (2, 3)  # Dubai -> Djibouti, same as amazon_sync.py
NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def slug_of(sku):
    """Product alias of a MedX SKU, or None for any other SKU."""
    m = SKU_RE.match((sku or "").strip())
    return m.group(1) if m else None


def parse(html):
    """The facts we need from a product page, or {"error": ...} when the layout is not the expected one."""
    m = NEXT_RE.search(html)
    if not m:
        return {"error": "no page data"}
    try:
        d = json.loads(m.group(1))["props"]["pageProps"]["productData"]
        price = float(d["price"])
        qty = d["quantity"]
    except (ValueError, KeyError, TypeError):
        return {"error": "unexpected page layout"}
    if not isinstance(qty, int) or isinstance(qty, bool):
        return {"error": "unexpected stock value"}
    return {"aed": price, "qty": qty, "publish": bool(d.get("publish")) and not d.get("deletedAt"),
            "name": d.get("name"), "updated": d.get("updatedAt"), "sourceDays": DUBAI_DAYS}


def fetch(slug, tries=3):
    """Reads https://www.medxpharmacy.com/product/<slug>/ -> parse() dict, {"gone": True} on 404, {"error": ...}."""
    err = "unknown"
    for n in range(tries):
        try:
            req = urllib.request.Request(f"{BASE}/product/{slug}/", headers={"User-Agent": UA, "Accept-Language": "en"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return parse(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"gone": True}
            err = f"HTTP {e.code}"
        except Exception as e:  # timeouts, resets, TLS
            err = type(e).__name__
        time.sleep(3 * (n + 1))
    return {"error": err}


def sellable(page, on_sale):
    """on_sale: the variant is currently sold (CONTINUE). Hysteresis between MIN_QTY and BACK_QTY."""
    if page.get("gone") or page.get("error"):
        return False
    if not page["publish"] or page["aed"] <= 0:
        return False
    return page["qty"] >= (MIN_QTY if on_sale else BACK_QTY)


def eta():
    """Delivery in Djibouti as "a-b" days: Dubai leg + forwarding (same format as amazon_sync.delivery_eta)."""
    return f"{DUBAI_DAYS + FORWARD_DAYS[0]}-{DUBAI_DAYS + FORWARD_DAYS[1]}"
