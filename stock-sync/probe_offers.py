#!/usr/bin/env python3
"""One-off probe: which way of reading the Amazon.ae "all offers" list works from a runner (prints what each returns)."""
import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser_fetch

asin = sys.argv[1]
r = browser_fetch.BrowserReader().start()
print("location:", r.location_text())
p = r.page
r.get(f"https://www.amazon.ae/dp/{asin}?language=en_AE")
print("product page loaded:", p.url[-60:])
flat = lambda t: re.sub(r"\s+", " ", t)
ajax = (f"https://www.amazon.ae/gp/product/ajax/ref=dp_aod_NEW_mbc?asin={asin}&m=&qid=&smid=&sourcecja="
        "&condition=NEW&experienceId=aodAjaxMain&pc=dp&language=en_AE")
# 1. same-origin XHR from the product page, like the panel itself does
try:
    t = p.evaluate("""async (u) => { const r = await fetch(u, {headers: {'x-requested-with': 'XMLHttpRequest'}, credentials: 'include'});
                       return r.status + ' ' + (await r.text()); }""", ajax)
    print("1 in-page fetch:", len(t), "bytes,", t.count('id="aod-offer"'), "offers;", flat(t[:400]))
except Exception as e:
    print("1 in-page fetch failed:", type(e).__name__, str(e)[:100])
# 2. legacy offer listing page
for url in (f"https://www.amazon.ae/gp/offer-listing/{asin}/ref=dp_olp_NEW_mbc?condition=NEW&language=en_AE",):
    try:
        p.goto(url, wait_until="domcontentloaded")
        p.wait_for_timeout(4000)
        h = p.content()
        print("2 offer-listing:", p.url[-70:], len(h), "bytes;", h.count("olpOffer"), "olpOffer;", h.count("aod-offer"), "aod-offer;",
              flat(p.inner_text("body"))[:300])
    except Exception as e:
        print("2 offer-listing failed:", type(e).__name__, str(e)[:100])
# 3. what the product page itself says about other offers (Amazon.ae moved to a new "Buying options" design)
try:
    p.goto(f"https://www.amazon.ae/dp/{asin}?language=en_AE", wait_until="load")
    p.wait_for_timeout(5000)
    h = p.content()
    ids = sorted(set(re.findall(r'\bid="([^"]*(?:offer|aod|olp|buying|mbc|odf)[^"]*)"', h, re.I)))
    print("3 ids:", len(ids), ids[:70])
    body = flat(p.inner_text("body"))
    for kw in ("Buying options", "Other sellers", "buying choices", "New & Used", "Sold by", "Ships from"):
        for m in list(re.finditer(re.escape(kw), body))[:2]:
            print(f"   body near [{kw}]:", body[max(0, m.start() - 120):m.start() + 330])
    for sel in ("#all-offers-display-params", "#all-offers-display-reload-param", "#olpLinkWidget_feature_div",
                "#buybox-see-all-buying-choices", "#all-offers-display"):
        try:
            outer = p.locator(sel).first.evaluate("e => e.outerHTML")
            print(f"   {sel}:", flat(outer)[:700])
        except Exception as e:
            print(f"   {sel}: not readable ({type(e).__name__})")
    for m in list(re.finditer(r"(?:ajax|aod)[A-Za-z]*(?:Url|URL|Path|Endpoint)[\"']?\s*[:=]\s*[\"'][^\"']{5,160}", h))[:8]:
        print("   js:", m.group(0)[:200])
    for m in list(re.finditer(r"/gp/[a-z/-]*aod[^\"'\s<>]{0,120}", h))[:8]:
        print("   path:", m.group(0)[:160])
r.close()
