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
# 3. product page with aod=1 and a long wait, then everything that mentions seller/offers
try:
    p.goto(f"https://www.amazon.ae/dp/{asin}?aod=1&language=en_AE", wait_until="load")
    p.wait_for_timeout(8000)
    h = p.content()
    print("3 aod=1 after load+8s:", len(h), "bytes;", h.count("aod-offer"), "aod markers;", h.count("a-offscreen"), "prices")
    body = flat(p.inner_text("body"))
    for kw in ("Other sellers", "buying choices", "Buying Choices", "Ships from", "Sold by"):
        k = body.find(kw)
        if k >= 0:
            print("   body near", kw, ":", body[max(0, k - 150):k + 250])
            break
except Exception as e:
    print("3 failed:", type(e).__name__, str(e)[:100])
r.close()
