#!/usr/bin/env python3
"""PadelShop.ae (Dubai) as a third supplier: reads one product page (padel rackets and balls).

A PadelShop variant is recognised by its SKU "PSAE-<product handle>" (the handle is the last part of
https://padelshop.ae/products/<handle>). padelshop.ae is a public Shopify store: /products/<handle>.js is plain JSON with
the price (in fils, AED x 100, VAT included) and an "available" flag for the variant. It does NOT show a stock quantity,
so "available" is the only signal: a variant is sellable only when the page was read just now and says available.
The shop prepares orders in 1 to 2 working days and delivers inside the UAE, so the Dubai leg is counted as 2 days
(PADELSHOP_DAYS) and the shop label stays "4 à 5 jours".

Safety rules (same lesson as Amazon.ae and MedX: never sell what is not confirmed):
  - a page that cannot be read (network, block, unexpected layout) never changes anything; coverage.py then sets the
    variant to Épuisé when it has not been read for PADELSHOP_STALE_HOURS hours;
  - a page that no longer exists (404) means the product was removed: not sellable.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

BASE = "https://padelshop.ae"
SKU_RE = re.compile(r"^PSAE-([a-z0-9][a-z0-9-]*)$")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
STALE_HOURS = int(os.environ.get("PADELSHOP_STALE_HOURS", "3"))  # coverage.py: unread for this long = Épuisé
DUBAI_DAYS = int(os.environ.get("PADELSHOP_DAYS", "2"))  # preparation 1-2 working days + delivery in the UAE
FORWARD_DAYS = (2, 3)  # Dubai -> Djibouti, same as amazon_sync.py


def slug_of(sku):
    """Product handle of a PadelShop SKU, or None for any other SKU."""
    m = SKU_RE.match((sku or "").strip())
    return m.group(1) if m else None


def parse(text):
    """The facts we need from the .js JSON, or {"error": ...} when it is not the expected layout."""
    try:
        d = json.loads(text)
        variants = d["variants"]
        price = min(float(v["price"]) for v in variants) / 100.0  # fils -> AED
        avail = any(bool(v["available"]) for v in variants)
    except (ValueError, KeyError, TypeError):
        return {"error": "unexpected page layout"}
    if not isinstance(d.get("available"), bool) or price < 0:
        return {"error": "unexpected availability value"}
    # qty is a stand-in (the shop shows no quantity) so the report columns of the MedX code keep working
    return {"aed": price, "qty": 1 if avail else 0, "available": avail, "publish": True, "name": d.get("title"),
            "sourceDays": DUBAI_DAYS}


def fetch(slug, tries=3):
    """Reads https://padelshop.ae/products/<slug>.js -> parse() dict, {"gone": True} on 404, {"error": ...}."""
    err = "unknown"
    for n in range(tries):
        try:
            req = urllib.request.Request(f"{BASE}/products/{slug}.js", headers={"User-Agent": UA, "Accept-Language": "en"})
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


def sellable(page, on_sale=False):
    """The variant is sold only if the page was read, exists and says available (no stock figure, no hysteresis)."""
    if page.get("gone") or page.get("error"):
        return False
    return bool(page["available"]) and page["aed"] > 0


def eta():
    """Delivery in Djibouti as "a-b" days: UAE leg + forwarding (same format as amazon_sync.delivery_eta)."""
    return f"{DUBAI_DAYS + FORWARD_DAYS[0]}-{DUBAI_DAYS + FORWARD_DAYS[1]}"
