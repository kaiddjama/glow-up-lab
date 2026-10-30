"""Probe: can noon.com UAE be read from a GitHub runner, and what do its search and product pages look like?

Prints, for a few searches: HTTP status, whether a block page appears, the product links found on the search page and,
for the first one, title / price / delivery / stock text. Nothing is written anywhere.
Usage: python3 -I probe_noon.py "query one" "query two" ...
"""
import re
import sys
import time
import urllib.parse

from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")


def squash(t):
    return re.sub(r"\s+", " ", t or "").strip()


def main():
    queries = sys.argv[1:] or ["essence 8h matte comfort lip liner"]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(user_agent=UA, locale="en-AE", timezone_id="Asia/Dubai",
                                  viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        page.set_default_timeout(25000)
        page.route("**/*", lambda r: r.abort() if r.request.resource_type in ("image", "media", "font") else r.continue_())
        for q in queries:
            url = "https://www.noon.com/uae-en/search/?q=" + urllib.parse.quote(q)
            print("\n=== SEARCH:", q, "|", url)
            try:
                resp = page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(5000)
            except Exception as e:
                print("goto failed:", type(e).__name__, str(e)[:150])
                continue
            html = page.content()
            print("status:", resp.status if resp else None, "| title:", squash(page.title())[:100], "| html size:", len(html))
            text = squash(page.inner_text("body"))
            if re.search(r"access denied|captcha|verify you are human|unusual traffic|blocked", text, re.I):
                print("BLOCK-LIKE TEXT:", text[:300])
            links = page.eval_on_selector_all(
                "a[href*='/p/']", "els => els.map(e => [e.href, (e.innerText || e.getAttribute('title') || '').trim()])")
            seen, products = set(), []
            for href, label in links:
                key = href.split("?")[0]
                if key not in seen:
                    seen.add(key)
                    products.append((key, squash(label)[:120]))
            print("product links:", len(products))
            for key, label in products[:8]:
                print("  ", key, "|", label)
            if not products:
                print("body text sample:", text[:400])
                continue
            print("--- first product page")
            try:
                page.goto(products[0][0], wait_until="domcontentloaded")
                page.wait_for_timeout(5000)
            except Exception as e:
                print("product goto failed:", type(e).__name__)
                continue
            ptext = squash(page.inner_text("body"))
            h1 = squash(page.inner_text("h1")) if page.locator("h1").count() else ""
            print("h1:", h1[:150])
            for pat in (r"AED\s*[\d,]+(?:\.\d+)?", r"(?:Get it|Delivery|Arrives)[^.]{0,80}", r"(?:Out of stock|Sold out|Currently unavailable|In stock)",
                        r"(?:Sold by|Shipped by|noon Express|Marketplace)[^.]{0,60}"):
                print("  ", pat[:20], "->", re.findall(pat, ptext, re.I)[:4])
            qa = page.eval_on_selector_all("[data-qa]", "els => [...new Set(els.map(e => e.getAttribute('data-qa')))].slice(0, 40)")
            print("data-qa ids:", qa)
            time.sleep(4)
        browser.close()


if __name__ == "__main__":
    main()
