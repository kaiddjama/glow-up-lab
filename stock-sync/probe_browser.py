#!/usr/bin/env python3
"""Test whether a real headless browser reads Amazon.ae from this machine (no Shopify access, nothing is changed).

Usage: python3 probe_browser.py ASIN [ASIN ...]
Sets the Dubai delivery location, reads each product page slowly and prints what amazon_sync.py would see:
price, stock, seller, delivery date, plus how many pages were blocked.
DUMP_DIR=folder also saves every page (gzip) there, and FACTS=1 prints the raw markers the parser relies on
(page ASIN, variation values, delivery options, location): used to build the offline tests of test_amazon.py.
"""
import datetime as dt
import gzip
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("BROWSER_DEBUG", "1")
import amazon_sync as a  # noqa: E402
import browser_fetch as b  # noqa: E402


def text(x):
    return re.sub(r"<[^>]+>|\s+", " ", x).strip()


def facts(html):
    """Raw markers of a product page, one short line each."""
    out = []
    for name, rx in (("canonical", r'<link rel="canonical" href="([^"]+)"'),
                     ("input ASIN", r'<input[^>]*\bid="ASIN"[^>]*value="([^"]*)"'),
                     ("input ASIN (name)", r'<input[^>]*\bname="ASIN"[^>]*value="([^"]*)"'),
                     ("parentAsin", r'"parentAsin"\s*:\s*"([^"]*)"'),
                     ("parent_asin", r'"parent_asin"\s*:\s*"([^"]*)"'),
                     ("currentAsin", r'"currentAsin"\s*:\s*"([^"]*)"'),
                     ("current_asin", r'"current_asin"\s*:\s*"([^"]*)"'),
                     ("landingAsin", r'"landingAsin"\s*:\s*"([^"]*)"'),
                     ("selected_variations", r'"selected_variations"\s*:\s*(\{[^}]*\})'),
                     ("variationValues", r'"variationValues"\s*:\s*(\{.{0,400})'),
                     ("dimensions", r'"dimensions"\s*:\s*(\[[^\]]*\])'),
                     ("dimensionsDisplay", r'"dimensionsDisplay"\s*:\s*(\[[^\]]*\])'),
                     ("location (html)", r'id="glow-ingress-line2"[^>]*>(.*?)</span>'),
                     ("title tag", r"<title>(.*?)</title>")):
        found = re.findall(rx, html, re.S)
        if found:
            uniq = []
            for f in found:
                f = text(f)[:300]
                if f not in uniq:
                    uniq.append(f)
            out.append(f"{name} x{len(found)}: {uniq[:3]}")
    m = re.search(r'id="productTitle"[^>]*>(.*?)</span>', html, re.S)
    out.append("productTitle: " + (text(m.group(1))[:160] if m else "NONE"))
    for m in re.finditer(r'id="(variation_[a-z_]+|inline-twister-expanded-dimension-text-[a-z_]+|inline-twister-dim-title-[a-z_]+)"', html):
        out.append(f"{m.group(1)}: {text(html[m.end():m.end() + 500])[:120]}")
    m = re.search(r'id="availability".*?</div>', html, re.S)
    out.append("availability: " + (text(m.group(0))[:200] if m else "NONE"))
    i = html.find('id="desktop_buybox"')
    out.append(f"desktop_buybox at {i} of {len(html)}")
    for m in re.finditer(r"<[^>]*data-csa-c-delivery-time=[^>]*>", html):
        attrs = dict(re.findall(r'(data-csa-c-[a-z-]+)="([^"]*)"', m.group(0)))
        keep = {k.replace("data-csa-c-", ""): v for k, v in attrs.items()
                if k in ("data-csa-c-delivery-time", "data-csa-c-delivery-price", "data-csa-c-delivery-type",
                         "data-csa-c-delivery-condition", "data-csa-c-mir-type", "data-csa-c-content-id",
                         "data-csa-c-delivery-benefit-program-id", "data-csa-c-delivery-cutoff")}
        after = text(html[m.end():m.end() + 400])[:110]
        out.append(f"delivery tag at {m.start()} ({'in' if 0 <= i <= m.start() <= i + 30000 else 'OUT OF'} buy box): {keep} | {after}")
    q = re.search(r'<select[^>]*name="quantity"[^>]*>(.*?)</select>', html, re.S)
    if q:
        opts = re.findall(r'<option[^>]*value="(\d+)"', q.group(1))
        out.append(f"quantity options: max {max(map(int, opts)) if opts else None} ({len(opts)} options)")
    for name, needle in (("outOfStock", 'id="outOfStock"'), ("apex-pricetopay-value", "apex-pricetopay-value"),
                         ("priceAmount", '"priceAmount"'), ("sellerProfileTriggerId", 'id="sellerProfileTriggerId"'),
                         ("merchantInfoFeature", 'id="merchantInfoFeature_feature_div"'),
                         ("Currently unavailable", "Currently unavailable"),
                         ("see all buying choices", "buybox-see-all-buying-choices"),
                         ("Page Not Found", "Page Not Found"), ("dogsofamazon", "dogsofamazon"),
                         ("first order", "first order"), ("add-to-cart-button", 'id="add-to-cart-button"'),
                         ("buy-now-button", 'id="buy-now-button"'), ("twister", 'id="twister'),
                         ("captcha", "captcha"), ("Only N left", "left in stock")):
        n = html.count(needle)
        if n:
            j = html.find(needle)
            out.append(f"marker {name} x{n}, first at {j}: {text(html[max(0, j - 60):j + 160])[:150]}")
    m = re.search(r'id="merchantInfoFeature_feature_div".{0,3000}', html, re.S)
    if m:
        out.append("merchant info: " + text(m.group(0))[:200])
    for m in re.finditer(r'offer-display-feature-text-message[^>]*>(.*?)</span>', html, re.S):
        out.append("offer display: " + text(m.group(1))[:100])
    return out


def main():
    asins = sys.argv[1:]
    delay = float(os.environ.get("DELAY", "8"))
    dump = os.environ.get("DUMP_DIR")
    if dump:
        os.makedirs(dump, exist_ok=True)
    start = time.time()
    ok = blocked = other = 0
    with b.BrowserReader() as r:
        print("Location:", r.location_text())
        for n, asin in enumerate(asins, 1):
            today = dt.datetime.now(dt.timezone(dt.timedelta(hours=4))).date()  # Dubai date, as in amazon_sync.py
            html = ""
            try:
                html = r.get(f"https://www.amazon.ae/dp/{asin}?language=en_AE")
                pg = a.parse(html, today)
            except Exception as e:
                pg = {"error": f"{type(e).__name__}: {e}"[:100]}
            if pg.get("error") == "captcha":
                blocked += 1
            elif pg.get("error"):
                other += 1
            else:
                ok += 1
            print(n, asin, {k: v for k, v in pg.items() if v not in (None, "", [])}, flush=True)
            print("   http", r.last_status, "| url", r.page.url[:120], "| html", len(html), flush=True)
            if os.environ.get("FACTS") == "1" and html:
                for line in facts(html):
                    print("   .", line, flush=True)
            if dump and html:
                with gzip.open(os.path.join(dump, f"{asin}.html.gz"), "wt", encoding="utf-8") as f:
                    f.write(html)
            time.sleep(delay + random.uniform(0, delay / 2))
        print("Location at the end:", r.location_text())
    print(f"read {ok}, captcha {blocked}, other errors {other}, of {len(asins)} in {int(time.time() - start)} s")


if __name__ == "__main__":
    main()
