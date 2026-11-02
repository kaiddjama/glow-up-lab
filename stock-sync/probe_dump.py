"""Diagnostic only: prints what the Amazon.ae buy box says about delivery (all dates, seller, shipping) for ASINs."""
import re
import sys

from browser_fetch import BrowserReader


def text(html):
    return re.sub(r"\s+", " ", re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I))


def main(asins):
    with BrowserReader() as r:
        print("location:", r.location_text())
        for a in asins:
            html = r.get(f"https://www.amazon.ae/dp/{a}?language=en_AE")
            i = html.find('id="desktop_buybox"')
            zone = html[i:i + 30000] if i >= 0 else html
            print("=" * 100)
            print("ASIN", a, "| buybox found:", i >= 0, "| html", len(html))
            print("title:", re.sub(r"<[^>]+>|\s+", " ", (re.search(r'id="productTitle".*?</span>', html, re.S) or [""])[0])[:100])
            print("delivery-time attrs:", re.findall(r'data-csa-c-delivery-time="([^"]*)"', zone))
            print("delivery-type attrs:", re.findall(r'data-csa-c-delivery-type="([^"]*)"', zone)[:8])
            print("delivery-price attrs:", re.findall(r'data-csa-c-delivery-price="([^"]*)"', zone)[:8])
            print("whole-page delivery-time attrs:", re.findall(r'data-csa-c-delivery-time="([^"]*)"', html)[:12])
            print("sold by / ships from:", re.findall(r'(?:sellerProfileTriggerId|merchant-info)[^>]*>\s*([^<]{2,60})', html)[:4])
            print("availability:", re.sub(r"<[^>]+>|\s+", " ", (re.search(r'id="availability".*?</div>', html, re.S) or [""])[0])[:120])
            # visible delivery wording
            for m in re.finditer(r"(FREE delivery|delivery|Delivery)[^<]{0,120}", text(zone)):
                pass
            blk = text(re.sub(r"<[^>]+>", " ", zone))
            for m in re.finditer(r"[^.]{0,80}(?:delivery|Delivery|deliver)[^.]{0,140}", blk):
                print("  >>", m.group(0).strip()[:220])
                if m.start() > 6000:
                    break
            m = re.search(r'otherSellers|aod-ingress-link|Other sellers[^<]{0,80}', html)
            print("other sellers link:", bool(m), "|", re.sub(r"<[^>]+>|\s+", " ", html[m.start():m.start() + 300])[:200] if m else "")


if __name__ == "__main__":
    main(sys.argv[1:])
