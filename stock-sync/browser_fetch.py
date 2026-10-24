"""Real-browser reader for Amazon.ae pages, used by amazon_sync.py when FETCHER=browser.

Starts headless Chromium (Playwright), sets the delivery location to a UAE city (default Dubai) like a visitor
would in the "Deliver to" pop-up, and returns the HTML of product pages. The location is checked before
reading starts and again every CHECK_EVERY pages: if the page no longer shows the city, reading stops
(LocationLost) so no delivery date from another location is ever used.

Settings (environment): BROWSER_CITY (default Dubai), BROWSER_HEADLESS=0 for a visible window,
BROWSER_PROFILE (folder that keeps cookies between runs; default: a fresh profile each run), BROWSER_DEBUG=1.
"""
import os
import random
import re
import time

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")
HOME = "https://www.amazon.ae/?language=en_AE"
LOCATION_LINK = "#nav-global-location-popover-link"
LOCATION_TEXT = "#glow-ingress-line2"
CHECK_EVERY = 25


class LocationLost(RuntimeError):
    pass


class Captcha(RuntimeError):
    pass


def debug(*a):
    if os.environ.get("BROWSER_DEBUG") == "1":
        print("[browser]", *a, flush=True)


class BrowserReader:
    def __init__(self):
        self.city = os.environ.get("BROWSER_CITY", "Dubai")
        self.pw = self.ctx = self.page = None
        self.count = 0
        self.city_picked = False

    def start(self):
        from playwright.sync_api import sync_playwright  # imported here: the HTTP-only sync does not need it
        self.pw = sync_playwright().start()
        opts = dict(headless=os.environ.get("BROWSER_HEADLESS", "1") != "0", args=["--lang=en-AE"])
        ctx_opts = dict(user_agent=UA, locale="en-AE", timezone_id="Asia/Dubai",
                        viewport={"width": 1366, "height": 900}, extra_http_headers={"Accept-Language": "en-AE,en;q=0.9"})
        profile = os.environ.get("BROWSER_PROFILE")
        if profile:
            self.ctx = self.pw.chromium.launch_persistent_context(profile, **opts, **ctx_opts)
        else:
            self.ctx = self.pw.chromium.launch(**opts).new_context(**ctx_opts)
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(20000)
        self.set_location()
        return self

    def close(self):
        for c in (self.ctx, self.pw):
            try:
                c and (c.close() if hasattr(c, "close") else c.stop())
            except Exception:
                pass

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()

    # -- location ---------------------------------------------------------------------------------------
    def location_text(self):
        try:
            return re.sub(r"\s+", " ", self.page.inner_text(LOCATION_TEXT, timeout=5000)).strip()
        except Exception:
            return ""

    def location_ok(self):
        return self.city.lower() in self.location_text().lower()

    def _captcha(self):
        """True for a real CAPTCHA (characters to type)."""
        return self.page.locator("#captchacharacters").count() > 0

    def _clear_gate(self):
        """Amazon sometimes shows a 'Click the button below to continue shopping' page; a visitor just presses it."""
        p = self.page
        for _ in range(2):
            if self._captcha() or p.locator("form[action*='validateCaptcha']").count() == 0:
                return
            debug("continue-shopping page, pressing the button")
            try:
                p.click("form[action*='validateCaptcha'] button, form[action*='validateCaptcha'] input[type=submit]", timeout=5000)
            except Exception:
                return
            p.wait_for_load_state("domcontentloaded")
            p.wait_for_timeout(2500)

    def set_location(self):
        """Choose the UAE city in the Deliver-to pop-up. Raises LocationLost when it cannot be confirmed."""
        p = self.page
        p.goto(HOME, wait_until="domcontentloaded")
        p.wait_for_timeout(2500)
        self._clear_gate()
        debug("home title:", p.title(), "| location:", self.location_text(), "| html size:", len(p.content()))
        if self._captcha():
            debug("page text:", re.sub(r"\s+", " ", p.inner_text("body"))[:300])
            raise Captcha("captcha on the home page")
        if self.location_ok():
            return
        p.click(LOCATION_LINK)
        p.wait_for_timeout(2500)
        selects = p.evaluate("""() => [...document.querySelectorAll('select')].map(s => ({id: s.id, name: s.name,
            visible: !!(s.offsetWidth || s.offsetHeight), options: [...s.options].slice(0, 60).map(o => o.text.trim())}))""")
        debug("selects in the pop-up:", selects)
        debug("pop-up buttons:", p.evaluate("""() => [...document.querySelectorAll(
            '.a-popover button, .a-popover input[type=submit], .a-popover .a-button-text, .a-popover a')]
            .map(b => (b.id || '') + ':' + (b.innerText || b.value || '').trim().slice(0, 40)).filter(x => x.length > 1).slice(0, 40)"""))
        debug("pop-up text:", p.evaluate("() => [...document.querySelectorAll('.a-popover')].map(e => e.innerText.replace(/\\s+/g, ' ').slice(0, 600)).join(' || ')"))
        debug("pop-up ids:", p.evaluate("() => [...document.querySelectorAll('.a-popover [id]')].map(e => e.id + '<' + e.tagName.toLowerCase() + '.' + (e.className + '').slice(0, 30)).slice(0, 120)"))
        if self._pick_in_dropdowns():
            selects = []
        done = False
        for s in selects:
            match = next((o for o in s["options"] if self.city.lower() in o.lower()), None)
            if match and s["visible"]:
                sel = f"select#{s['id']}" if s["id"] else f"select[name='{s['name']}']"
                p.select_option(sel, label=match)
                debug("selected", match, "in", sel)
                p.wait_for_timeout(1500)
                done = True
                break
        if not done and not self.city_picked:
            raise LocationLost(f"no {self.city} choice found in the Deliver-to pop-up (see BROWSER_DEBUG output)")
        for sel in ("#GLUXConfirmClose", "input[aria-labelledby='GLUXZipUpdate-announce']",
                    ".a-popover-footer button", "button:has-text('Done')", "button:has-text('Apply')",
                    "span:has-text('Done') >> nth=0"):
            try:
                p.click(sel, timeout=2500)
                debug("clicked", sel)
                break
            except Exception:
                continue
        p.wait_for_timeout(2500)
        p.goto(HOME, wait_until="domcontentloaded")
        p.wait_for_timeout(2000)
        debug("location after change:", self.location_text())
        if not self.location_ok():
            raise LocationLost(f"delivery location is '{self.location_text()}', not {self.city}")

    def _pick_in_dropdowns(self):
        """Custom (non-native) Amazon dropdowns: open each one that is not the country list, choose the city."""
        p = self.page
        for i in range(4):
            boxes = p.locator(".a-popover span.a-button-dropdown:visible")
            n = boxes.count()
            debug("dropdown boxes:", [(boxes.nth(k).get_attribute("id"), boxes.nth(k).inner_text().strip()[:30]) for k in range(n)])
            progressed = False
            for k in range(n):
                box = boxes.nth(k)
                bid = box.get_attribute("id") or ""
                if "Country" in bid:
                    continue
                box.click()
                p.wait_for_timeout(1200)
                items = p.locator("a.a-dropdown-link:visible")
                texts = [items.nth(j).inner_text().strip() for j in range(min(items.count(), 80))]
                debug("dropdown", bid, "items:", texts[:40])
                idx = next((j for j, t in enumerate(texts) if self.city.lower() in t.lower()), None)
                if idx is None and i > 0:
                    idx = next((j for j, t in enumerate(texts) if t and t.lower() != "choose"), None)
                if idx is None:
                    p.keyboard.press("Escape")
                    continue
                items.nth(idx).click()
                debug("chose", texts[idx])
                p.wait_for_timeout(1500)
                self.city_picked = progressed = True
                break
            if not progressed:
                break
        return self.city_picked

    # -- reading ----------------------------------------------------------------------------------------
    def get(self, url):
        """HTML of a page. Raises LocationLost if the delivery location is no longer the chosen city."""
        self.count += 1
        p = self.page
        p.goto(url, wait_until="domcontentloaded")
        self._clear_gate()
        try:
            p.wait_for_selector("#productTitle, form[action*='validateCaptcha']", timeout=15000)
        except Exception:
            pass
        p.wait_for_timeout(int(random.uniform(800, 1800)))  # lets the buy box and delivery block render
        if self.count % CHECK_EVERY == 0 and "/dp/" in url and not self.location_ok():
            raise LocationLost(f"delivery location changed to '{self.location_text()}'")
        return p.content()
