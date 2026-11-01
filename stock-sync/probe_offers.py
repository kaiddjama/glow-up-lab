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
# 1. same-origin XHR from the product page, like the panel itself does: which address answers?
cands = [
    f"/gp/aod/ajax/ref=aod_f_new?asin={asin}&m=&qid=&smid=&sourcecja=&pc=dp&language=en_AE",
    f"/gp/aod/ajax?asin={asin}&pc=dp&isonlyrenderofferlist=true&language=en_AE",
    f"/gp/aod/ajax/ref=dp_aod_NEW_mbc?asin={asin}&m=&qid=&smid=&sourcecja=&pc=dp&language=en_AE",
    f"/gp/product/ajax?asin={asin}&experienceId=aodAjaxMain&pc=dp&isonlyrenderofferlist=true&language=en_AE",
    f"/gp/product/ajax/ref=aod_f_new?asin={asin}&m=&qid=&smid=&sourcecja=&filters=%7B%22all%22%3Atrue%2C%22new%22%3Atrue%7D&experienceId=aodAjaxMain&language=en_AE",
]
for u in cands:
    try:
        t = p.evaluate("""async (u) => { const r = await fetch(u, {headers: {'x-requested-with': 'XMLHttpRequest'}, credentials: 'include'});
                           return r.status + ' ' + (await r.text()); }""", u)
        print("1", u[:75], "->", len(t), "bytes,", t.count('id="aod-offer"'), "offers,", t.count("aod-pinned-offer"), "pinned;", flat(t[:150]))
    except Exception as e:
        print("1", u[:75], "failed:", type(e).__name__, str(e)[:100])
r.close()
