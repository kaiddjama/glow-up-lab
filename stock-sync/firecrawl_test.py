"""Test only: reads Amazon.ae product pages through a self-hosted Firecrawl (http://localhost:3002) and prints what
the stock-sync robot needs: delivery location, price, stock, free delivery date vs paid express. Nothing is changed."""
import json
import re
import sys
import time
import urllib.request

API = "http://localhost:3002"


def post(path, body, timeout=180):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"success": False, "http": e.code, "error": e.read().decode()[:400]}
    except Exception as e:
        return {"success": False, "error": repr(e)[:300]}


def summarize(html):
    loc = re.search(r'id="glow-ingress-line2"[^>]*>\s*([^<]+)', html)
    price = re.search(r'apex-pricetopay-value.{0,400}?a-price-whole">([\d,]+)', html, re.S)
    tags = re.findall(r"<[^>]*data-csa-c-delivery-time=[^>]*>", html)
    opts = [(re.search(r'delivery-time="([^"]*)"', t).group(1),
             (re.search(r'delivery-price="([^"]*)"', t) or [None, ""])[1]) for t in tags]
    return {"html": len(html), "title": 'id="productTitle"' in html, "captcha": "captchacharacters" in html,
            "location": loc.group(1).strip() if loc else None, "price": price.group(1) if price else None,
            "delivery_options": opts,
            "sold_by": re.findall(r'sellerProfileTriggerId"[^>]*>\s*([^<]+)', html)[:1]}


def main(asins):
    for _ in range(60):  # wait for the API
        try:
            urllib.request.urlopen(API + "/", timeout=5)
            break
        except Exception:
            time.sleep(5)
    for a in asins:
        url = f"https://www.amazon.ae/dp/{a}?language=en_AE"
        print("=" * 90, "\nASIN", a)
        t = time.time()
        r = post("/v1/scrape", {"url": url, "formats": ["rawHtml"], "waitFor": 3000,
                                "headers": {"Accept-Language": "en-AE,en;q=0.9"}})
        print("plain scrape: success", r.get("success"), f"{time.time() - t:.0f}s", r.get("error", ""))
        if r.get("success"):
            print("  ", summarize(r["data"].get("rawHtml", "")))
        # location needs the Deliver-to pop-up: try Firecrawl actions
        acts = [{"type": "click", "selector": "#nav-global-location-popover-link"}, {"type": "wait", "milliseconds": 2000},
                {"type": "click", "selector": "#GLUXCityWithDistrictCityInput"}, {"type": "write", "text": "Dubai"},
                {"type": "wait", "milliseconds": 2000}]
        r = post("/v1/scrape", {"url": url, "formats": ["rawHtml"], "actions": acts})
        print("with actions: success", r.get("success"), (r.get("error") or "")[:300])
        if r.get("success"):
            print("  ", summarize(r["data"].get("rawHtml", "")))


if __name__ == "__main__":
    main(sys.argv[1:])
