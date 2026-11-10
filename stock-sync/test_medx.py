#!/usr/bin/env python3
"""Offline checks of medx.py (no network): python3 -I test_medx.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import medx  # noqa: E402


def page(price="95", qty=40, publish=True, deleted=None):
    data = {"props": {"pageProps": {"productData": {"price": price, "quantity": qty, "publish": publish, "deletedAt": deleted,
                                                    "name": "x", "updatedAt": "2026-11-10T00:00:00Z"}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def check(cond, msg):
    if not cond:
        sys.exit("FAIL: " + msg)


check(medx.slug_of("MEDX-abe-pre-workout-375g") == "abe-pre-workout-375g", "slug")
check(medx.slug_of("AMZ-B0853SHPL9") is None and medx.slug_of(None) is None and medx.slug_of("MEDX-") is None, "not a MedX sku")
ok = medx.parse(page())
check(ok["aed"] == 95.0 and ok["qty"] == 40 and ok["publish"], "parse")
check(medx.parse("<html></html>").get("error"), "no data is an error, never 'out of stock'")
check(medx.parse(page(qty="12")).get("error"), "stock must be a number")
check(medx.parse(page(price="abc")).get("error"), "bad price is an error")
check(not medx.parse(page(deleted="2026-11-01"))["publish"], "deleted page is not published")
# sellable: threshold 8 when on sale, 12 to come back (defaults)
check(medx.sellable(medx.parse(page(qty=8)), True), "8 left stays on sale")
check(not medx.sellable(medx.parse(page(qty=7)), True), "7 left goes Épuisé")
check(not medx.sellable(medx.parse(page(qty=11)), False), "11 left does not come back")
check(medx.sellable(medx.parse(page(qty=12)), False), "12 left comes back")
check(not medx.sellable(medx.parse(page(publish=False)), True), "unpublished is not sellable")
check(not medx.sellable({"gone": True}, True) and not medx.sellable({"error": "HTTP 503"}, True), "gone / error never sellable")
check(not medx.sellable(medx.parse(page(price="0")), True), "price 0 is not sellable")
check(medx.eta() == "3-4", "eta")
# selection.json: every entry is complete and nothing can collide
HERE = os.path.dirname(os.path.abspath(__file__))
sel = json.load(open(os.path.join(HERE, "medx", "selection.json"), encoding="utf-8"))
slugs, handles = [], []
for p in sel:
    handles.append(p["handle"])
    check(p["title"] and p["intro"] and p["points"] and p["note"] and p["weight_g"] > 0, "incomplete entry " + p["handle"])
    labels = [v["label"] for v in p["variants"]]
    check(len(labels) == len(set(labels)), "two variants with the same label in " + p["handle"])
    for v in p["variants"]:
        slugs.append(v["slug"])
        check(medx.slug_of("MEDX-" + v["slug"]) == v["slug"], "bad alias " + v["slug"])
        check(v.get("weight_g", p["weight_g"]) > 0, "no weight for " + v["slug"])
        check(v["photo"].endswith(".jpg"), "photo name " + v["slug"])
check(len(handles) == len(set(handles)) and len(slugs) == len(set(slugs)), "duplicate handle or MedX page in the selection")
print("medx tests OK")
