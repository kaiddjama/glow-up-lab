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
        # Only the page text is needed: do not download pictures, video or fonts (less load on Amazon, faster pages).
        self.page.route("**/*", lambda route: route.abort()
                        if route.request.resource_type in ("image", "media", "font") else route.continue_())
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
        p.wait_for_selector("#GLUXCityWithDistrictCityInput", state="visible", timeout=10000)
        self._fill_city_and_district()
        p.wait_for_timeout(2500)
        for sel in ("#GLUXConfirmClose", "input#GLUXConfirmClose", "button:has-text('Continue')"):  # success dialog
            try:
                p.click(sel, timeout=3000)
                debug("clicked", sel)
                break
            except Exception:
                continue
        p.wait_for_timeout(2500)
        p.goto(HOME, wait_until="domcontentloaded")
        self._clear_gate()
        p.wait_for_timeout(2000)
        debug("location after change:", self.location_text())
        if not self.location_ok():
            raise LocationLost(f"delivery location is '{self.location_text()}', not {self.city}")

    def _suggestions(self, list_id):
        items = self.page.locator(f"#{list_id} li:visible")
        return items, [items.nth(i).inner_text().strip() for i in range(min(items.count(), 30))]

    def _fill_city_and_district(self):
        """The pop-up has two autocomplete boxes (city, then district) and an Apply button."""
        p = self.page
        p.click("#GLUXCityWithDistrictCityInput")
        p.keyboard.type(self.city, delay=90)
        p.wait_for_timeout(2000)
        items, texts = self._suggestions("GLUXCityWithDistrictCityList")
        debug("city suggestions:", texts)
        idx = next((i for i, t in enumerate(texts) if self.city.lower() in t.lower()), None)
        if idx is None:
            raise LocationLost(f"no {self.city} suggestion in the Deliver-to pop-up: {texts}")
        items.nth(idx).click()
        p.wait_for_timeout(1500)
        district = os.environ.get("BROWSER_DISTRICT", "")
        box = p.locator("#GLUXCityWithDistrict_DistrictInput")
        if box.is_visible():
            box.click()
            if district:
                p.keyboard.type(district, delay=90)
            p.wait_for_timeout(2000)
            items, texts = self._suggestions("GLUXCityWithDistrict_DistrictList")
            debug("district suggestions:", texts[:15])
            if texts:
                items.nth(0).click()
                p.wait_for_timeout(1000)
        debug("pop-up inputs:", p.evaluate("() => [...document.querySelectorAll('#GLUXSpecifyLocationDiv input')].map(i => i.id + '=' + i.value)"))
        p.click("#GLUXCityWithDistrictApplyButton, #GLUXCityWithDistrictApplyButtonLabel")
        self.city_picked = True

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
