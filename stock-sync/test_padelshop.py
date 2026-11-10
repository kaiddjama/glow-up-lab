#!/usr/bin/env python3
"""Offline checks of padelshop.py (no network): python3 -I test_padelshop.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padelshop  # noqa: E402


def page(price=64950, available=True, top=True):
    return json.dumps({"title": "x", "available": top, "variants": [{"price": price, "available": available}]})


def check(cond, msg):
    if not cond:
        sys.exit("FAIL: " + msg)


check(padelshop.slug_of("PSAE-volt-700-padel-tennis-racket-2022-model") == "volt-700-padel-tennis-racket-2022-model", "slug")
check(padelshop.slug_of("B0FX4SYQQN") is None and padelshop.slug_of("MEDX-abe") is None and padelshop.slug_of(None) is None
      and padelshop.slug_of("PSAE-") is None, "not a PadelShop sku")
ok = padelshop.parse(page())
check(ok["aed"] == 649.5 and ok["available"], "parse (price is in fils)")
check(padelshop.parse("<html></html>").get("error"), "no JSON is an error, never 'out of stock'")
check(padelshop.parse(json.dumps({"variants": []})).get("error"), "no variant is an error")
check(padelshop.parse(page(price="abc")).get("error"), "bad price is an error")
check(padelshop.sellable(ok), "available is sellable")
check(not padelshop.sellable(padelshop.parse(page(available=False, top=False))), "unavailable is not sellable")
check(not padelshop.sellable({"gone": True}) and not padelshop.sellable({"error": "HTTP 503"}), "gone / error never sellable")
check(not padelshop.sellable(padelshop.parse(page(price=0))), "price 0 is not sellable")
check(padelshop.eta() == "4-5", "eta")
print("padelshop tests OK")
