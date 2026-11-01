#!/usr/bin/env python3
"""One-off probe: what happens on Amazon.ae when the "other sellers" link is clicked (prints the XHR/fetch calls)."""
import os
import re
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser_fetch

asin = sys.argv[1]
r = browser_fetch.BrowserReader().start()
print("location:", r.location_text())
p = r.page
flat = lambda t: re.sub(r"\s+", " ", t)
r.get(f"https://www.amazon.ae/dp/{asin}?language=en_AE")
calls = []
p.on("request", lambda q: calls.append(f"{q.method} {q.resource_type} {q.url.split('?')[0][-90:]} ?{q.url.split('?', 1)[1][:150] if '?' in q.url else ''}")
     if q.resource_type in ("xhr", "fetch") else None)
for sel in ("#aod-ingress-link", "#buybox-see-all-buying-choices a", "#olp_feature_div a", "#dynamic-aod-ingress-box a"):
    n = p.locator(sel).count()
    print("selector", sel, "matches", n)
    if n:
        try:
            print("  visible:", p.locator(sel).first.is_visible(), "| text:", flat(p.locator(sel).first.inner_text())[:80],
                  "| href:", (p.locator(sel).first.get_attribute("href") or "")[:100])
            p.locator(sel).first.scroll_into_view_if_needed(timeout=3000)
            p.locator(sel).first.click(timeout=4000)
        except Exception as e:
            print("  click failed:", type(e).__name__, str(e)[:100])
        p.wait_for_timeout(9000)
        print("  calls after click:", len(calls))
        for c in calls[:25]:
            print("   ", c)
        h = p.content()
        print("  after click: url", p.url[-70:], "| aod-offer markers:", h.count('id="aod-offer"'), "| pinned:", h.count("aod-pinned-offer"),
              "| #aod-container text:", flat(p.inner_text("#aod-container"))[:150] if p.locator("#aod-container").count() else "no container")
        break
r.close()
