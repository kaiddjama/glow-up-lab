#!/usr/bin/env python3
"""Full audit of the catalogue against what the stock sync is supposed to guarantee (see PROTOCOLE-INVENTAIRE.md).

It reads EVERY product (no sample) and checks, per product and per variant:
  - stock tracking is on (inventoryItem.tracked): without it Shopify ignores "Épuisé" (inventoryPolicy DENY) and the
    variant stays orderable. With FIX=1 it switches tracking on (quantity stays 0, policy untouched);
  - an Épuisé variant (DENY) is really not for sale (availableForSale false);
  - every active product was read on Amazon.ae (supplier.checked_at) and not longer than STALE_HOURS ago;
  - every sellable variant of an active product has an ASIN, and its own page was read (variant_checked_at) recently;
  - an active, read, sellable product is published on the Online Store (otherwise its page answers 404);
  - prices are present and positive (the price itself comes from the live Amazon.ae price at each sync).
Writes a markdown report (REPORT_FILE, and the job summary on GitHub). Exit code 1 = something Hoodo must know about
is still wrong after the automatic fixes.

Usage: python3 -I inventory_audit.py   (same environment as park_soldout.py; DRY_RUN=1 or FIX=0 reports only)
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I does not add the script folder
import amazon_sync as s  # noqa: E402

STALE_HOURS = float(os.environ.get("STALE_HOURS", "8"))  # five checks a day = one every ~5 h; coverage.py uses 6 h
PUBLICATION = os.environ.get("ONLINE_STORE_PUBLICATION", "gid://shopify/Publication/338148819125")
Q = """query($after:String,$pub:ID!){ products(first:40, after:$after, query:"-status:archived"){
  pageInfo{hasNextPage endCursor}
  nodes{ id handle title status tags createdAt isGiftCard
    pub: publishedOnPublication(publicationId:$pub)
    chk: metafield(namespace:"supplier", key:"checked_at"){value}
    ref: metafield(namespace:"internal", key:"supplier_ref"){value}
    variants(first:100){ nodes{ id title sku price inventoryPolicy availableForSale
      inventoryItem{ id tracked }
      vchk: metafield(namespace:"supplier", key:"variant_checked_at"){value} } } } } }"""
TRACK_M = """mutation($id:ID!){ inventoryItemUpdate(id:$id, input:{tracked:true}){ userErrors{field message} } }"""


def load():
    out, after = [], None
    while True:
        data = s.gql(Q, {"after": after, "pub": PUBLICATION})["products"]
        out += data["nodes"]
        if not data["pageInfo"]["hasNextPage"]:
            return out
        after = data["pageInfo"]["endCursor"]


def age_hours(meta, now):
    if not meta:
        return None
    t = dt.datetime.fromisoformat(meta["value"].replace("Z", "+00:00"))
    return (now - t).total_seconds() / 3600


def has_asin(p, v):
    if s.ASIN_RE.search(v.get("sku") or ""):
        return True
    return len(p["variants"]["nodes"]) == 1 and bool(p.get("ref") and s.ASIN_RE.search(p["ref"]["value"]))


def main():
    if not s.have_credentials():
        return
    fix = os.environ.get("FIX", "1") == "1" and os.environ.get("DRY_RUN") != "1"
    now = dt.datetime.now(dt.timezone.utc)
    products = load()
    by_status = {}
    for p in products:
        by_status[p["status"]] = by_status.get(p["status"], 0) + 1
    variants = [(p, v) for p in products for v in p["variants"]["nodes"]]

    untracked = [(p, v) for p, v in variants if not v["inventoryItem"]["tracked"] and not p["isGiftCard"]]  # gift cards cannot be tracked
    fixed, failed = 0, []
    if fix:
        for p, v in untracked:
            errs = s.gql(TRACK_M, {"id": v["inventoryItem"]["id"]})["inventoryItemUpdate"]["userErrors"]
            if errs:
                failed.append((p, v, errs))
            else:
                fixed += 1
    untracked_products = sorted({p["handle"] for p, _ in untracked})

    active = [p for p in products if p["status"] == "ACTIVE"]
    sellable = lambda p: [v for v in p["variants"]["nodes"] if v["inventoryPolicy"] == "CONTINUE"]  # noqa: E731
    deny_but_orderable = [(p, v) for p, v in variants if p["status"] == "ACTIVE" and v["inventoryPolicy"] == "DENY"
                          and v["availableForSale"] and not p["isGiftCard"]]
    never_read = [p for p in active if not p.get("chk") and sellable(p)]
    stale = [p for p in active if p.get("chk") and sellable(p) and age_hours(p["chk"], now) > STALE_HOURS]
    no_asin = [(p, v) for p in active for v in sellable(p) if not has_asin(p, v)]
    stale_var = [(p, v) for p in active if p.get("chk") for v in sellable(p)
                 if has_asin(p, v) and (age_hours(v.get("vchk"), now) is None or age_hours(v["vchk"], now) > STALE_HOURS)]
    unpublished = [p for p in active if p.get("chk") and sellable(p) and not p.get("pub")]
    bad_price = [(p, v) for p, v in variants if p["status"] == "ACTIVE" and v["inventoryPolicy"] == "CONTINUE"
                 and not (float(v["price"] or 0) > 0)]
    new = {p["handle"] for p in active if (now - dt.datetime.fromisoformat(p["createdAt"].replace("Z", "+00:00"))).days < 1}

    when = dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).strftime("%d/%m/%Y %Hh%M")
    L = [f"# Audit complet du stock — {when} (heure de Djibouti)", "",
         f"{len(products)} produits lus (hors archivés) : " + ", ".join(f"{k} {n}" for k, n in sorted(by_status.items()))
         + f" ; {len(variants)} variantes. Produits créés depuis moins de 24 h : {len(new)}.", "",
         "| Contrôle | Résultat |", "|---|---|",
         f"| Suivi du stock désactivé (variantes) | {len(untracked)} sur {len(variants)} dans {len(untracked_products)} produits"
         + (f" → {fixed} corrigées, {len(failed)} en échec" if fix else " (non corrigé : lecture seule)") + " |",
         f"| Épuisé (DENY) mais encore commandable | {len(deny_but_orderable)} |",
         f"| Produits actifs jamais lus sur Amazon.ae | {len(never_read)} |",
         f"| Produits actifs lus depuis plus de {STALE_HOURS:g} h | {len(stale)} |",
         f"| Variantes en vente sans ASIN | {len(no_asin)} |",
         f"| Variantes en vente dont la page n'a pas été lue depuis {STALE_HOURS:g} h | {len(stale_var)} |",
         f"| Produits vendables non publiés sur la Boutique en ligne (404) | {len(unpublished)} |",
         f"| Variantes en vente avec un prix absent ou nul | {len(bad_price)} |", ""]

    def section(title, handles, limit=60):
        if handles:
            L.append(f"## {title}")
            L.extend(f"- {h}" for h in sorted(handles)[:limit])
            if len(handles) > limit:
                L.append(f"- … et {len(handles) - limit} autres")
            L.append("")

    section("Suivi du stock désactivé (produits)", untracked_products)
    section("Échecs de correction du suivi", [f"{p['handle']}: {e}" for p, _, e in failed])
    section("Épuisé mais encore commandable", {p["handle"] for p, _ in deny_but_orderable})
    section("Actifs jamais lus", [p["handle"] for p in never_read])
    section("Actifs périmés", [f"{p['handle']} ({age_hours(p['chk'], now):.0f} h)" for p in stale])
    section("Variantes en vente sans ASIN", {p["handle"] for p, _ in no_asin})
    section("Variantes non relues", {p["handle"] for p, _ in stale_var})
    section("Non publiés (404)", [p["handle"] for p in unpublished])
    section("Prix absent ou nul", {p["handle"] for p, _ in bad_price})
    report = "\n".join(L)
    print(report)
    path = os.environ.get("REPORT_FILE")
    if path:
        open(path, "w", encoding="utf-8").write(report + "\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        open(summary, "a", encoding="utf-8").write(report + "\n")
    # what the owner must be told about: anything still wrong after the automatic fixes
    problems = []
    if failed or (untracked and not fix):
        problems.append(f"{len(failed) or len(untracked)} variantes sans suivi du stock")
    if deny_but_orderable:
        problems.append(f"{len(deny_but_orderable)} variantes Épuisé encore commandables")
    if never_read:
        problems.append(f"{len(never_read)} produits actifs jamais lus sur Amazon.ae")
    if no_asin:
        problems.append(f"{len(no_asin)} variantes en vente sans ASIN")
    if bad_price:
        problems.append(f"{len(bad_price)} variantes en vente sans prix")
    # stale pages alone are reported but do not fail: a full check takes ~45 min and the coverage step already handles them
    if len(stale) > 0.10 * max(1, len(active)):
        problems.append(f"{len(stale)} produits actifs non relus depuis plus de {STALE_HOURS:g} h")
    if problems and os.environ.get("DRY_RUN") != "1":
        print("PROBLEMS:", "; ".join(problems))
        sys.exit(1)


if __name__ == "__main__":
    main()
