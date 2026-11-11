#!/usr/bin/env python3
"""Full audit of the catalogue against what the stock sync is supposed to guarantee (see PROTOCOLE-INVENTAIRE.md).

It reads EVERY product (no sample) and checks, per product and per variant:
  - stock tracking is on (inventoryItem.tracked): without it Shopify ignores "Épuisé" (inventoryPolicy DENY) and the
    variant stays orderable. With FIX=1 it switches tracking on (quantity stays 0, policy untouched);
  - an Épuisé variant (DENY) is really not for sale (availableForSale false);
  - every active product was read on Amazon.ae (supplier.checked_at) and not longer than STALE_HOURS ago;
  - every sellable variant of an active product has an ASIN, or the reference of another source (SKU "MEDX-..." /
    "PSAE-...", read by their own syncs), and its own page was read (variant_checked_at) recently. Gift cards have neither;
  - an active, read, sellable product is published on the Online Store (otherwise its page answers 404);
  - prices are present and positive (the price itself comes from the live Amazon.ae price at each sync).
It also counts WHY the Amazon.ae variants are Épuisé and why products are hidden (the reason amazon_sync.py keeps on each
variant, supplier.sync_state "why"), so "why are so many products hidden?" has an answer every 30 minutes.
Writes a markdown report (REPORT_FILE, and the job summary on GitHub). Exit code 1 = something Hoodo must know about
is still wrong after the automatic fixes.

Usage: python3 -I inventory_audit.py   (same environment as park_soldout.py; DRY_RUN=1 or FIX=0 reports only)
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I does not add the script folder
import amazon_sync as s  # noqa: E402
import suppliers  # noqa: E402

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
      st: metafield(namespace:"supplier", key:"sync_state"){value}
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


def source_of(p, v):
    """Pure: where this variant is bought. "other" (MedX, PadelShop.ae: read by their own syncs), "amazon",
    "gift" (a gift card: nothing to buy) or None (nothing says where to buy it: it must not be on sale)."""
    if p.get("isGiftCard"):
        return "gift"
    if suppliers.is_other_source(v.get("sku")):
        return "other"
    return "amazon" if has_asin(p, v) else None


REASONS = (("rupture", "En rupture sur Amazon.ae"),
           ("amazon-now", "Seulement en Amazon Now (livraison en minutes à Dubaï, pas d'offre ordinaire)"),
           ("delai:4+", "Livraison à Dubaï en 4 jours ou plus"),
           ("delai:3", "Livraison à Dubaï en 3 jours (1 jour de trop)"), ("stock-bas", "Stock presque fini sur Amazon.ae"),
           ("sans-date", "Pas de date de livraison pour Dubaï (surtout des imports Amazon US / UK)"),
           ("retenue", "Retenue à la main (étiquette bloque ou seller-hold.json)"),
           ("pause-commande", "Pause de 24 h après une commande non commandable"),
           ("prix", "Saut de prix en attente d'une seconde lecture"),
           ("autre-article", "La page Amazon.ae affiche un autre article"), ("fiche-supprimee", "Fiche supprimée sur Amazon.ae"),
           ("sans-asin", "Variante sans ASIN"), ("?", "Motif pas encore noté (variante pas relue depuis l'ajout du motif)"))


def reason_of(p, v):
    """Pure: why this Épuisé variant of an Amazon.ae product is not sold, as amazon_sync.why_out wrote it."""
    if not has_asin(p, v):
        return "sans-asin"
    try:
        why = json.loads((v.get("st") or {}).get("value") or "{}").get("why")
    except (ValueError, AttributeError):
        why = None
    return why if why in dict(REASONS) else "?"


def reasons_table(products):
    """Pure: markdown lines counting the Épuisé Amazon.ae variants by reason, and the hidden products (draft + epuise-auto)
    by the reason most of their variants share."""
    by_var, by_prod = {}, {}
    for p in products:
        if p.get("isGiftCard"):
            continue
        mine = [reason_of(p, v) for v in p["variants"]["nodes"]
                if v["inventoryPolicy"] == "DENY" and not suppliers.is_other_source(v.get("sku"))]
        for why in mine:
            by_var[why] = by_var.get(why, 0) + 1
        if mine and p["status"] == "DRAFT" and s.OUT_TAG in [t.lower() for t in p.get("tags") or []]:
            top = max(set(mine), key=mine.count)
            by_prod[top] = by_prod.get(top, 0) + 1
    lines = ["## Pourquoi c'est en Épuisé (variantes Amazon.ae) et masqué (produits)", "",
             "| Motif | Variantes en Épuisé | Produits masqués |", "|---|---|---|"]
    lines += [f"| {label} | {by_var.get(code, 0)} | {by_prod.get(code, 0)} |" for code, label in REASONS
              if by_var.get(code) or by_prod.get(code)]
    lines += [f"| Total | {sum(by_var.values())} | {sum(by_prod.values())} |", ""]
    return lines


def stale_limit(p, v):
    """Pure: hours after which a variant on sale counts as not read again (each other source has its own limit)."""
    mod = suppliers.module_of(v.get("sku"))[0]
    return mod.STALE_HOURS if mod and not p.get("isGiftCard") else STALE_HOURS


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

    active = [p for p in products if p["status"] == "ACTIVE" and not p["isGiftCard"]]  # a gift card is not bought anywhere
    sellable = lambda p: [v for v in p["variants"]["nodes"] if v["inventoryPolicy"] == "CONTINUE"]  # noqa: E731
    deny_but_orderable = [(p, v) for p, v in variants if p["status"] == "ACTIVE" and v["inventoryPolicy"] == "DENY"
                          and v["availableForSale"] and not p["isGiftCard"]]
    never_read = [p for p in active if not p.get("chk") and sellable(p)]
    stale = [p for p in active if p.get("chk") and sellable(p) and age_hours(p["chk"], now) > STALE_HOURS]
    no_asin = [(p, v) for p in active for v in sellable(p) if not source_of(p, v)]
    stale_var = [(p, v) for p in active if p.get("chk") for v in sellable(p)
                 if source_of(p, v) and (age_hours(v.get("vchk"), now) is None or age_hours(v["vchk"], now) > stale_limit(p, v))]
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
         f"| Variantes en vente sans ASIN ni référence d'un autre fournisseur | {len(no_asin)} |",
         f"| Variantes en vente dont la page n'a pas été relue à temps ({STALE_HOURS:g} h Amazon.ae, moins pour MedX et PadelShop.ae) | {len(stale_var)} |",
         f"| Produits vendables non publiés sur la Boutique en ligne (404) | {len(unpublished)} |",
         f"| Variantes en vente avec un prix absent ou nul | {len(bad_price)} |", ""]

    def section(title, handles, limit=60):
        if handles:
            L.append(f"## {title}")
            L.extend(f"- {h}" for h in sorted(handles)[:limit])
            if len(handles) > limit:
                L.append(f"- … et {len(handles) - limit} autres")
            L.append("")

    L.extend(reasons_table(products))
    section("Suivi du stock désactivé (produits)", untracked_products)
    section("Échecs de correction du suivi", [f"{p['handle']}: {e}" for p, _, e in failed])
    section("Épuisé mais encore commandable", {p["handle"] for p, _ in deny_but_orderable})
    section("Actifs jamais lus", [p["handle"] for p in never_read])
    section("Actifs périmés", [f"{p['handle']} ({age_hours(p['chk'], now):.0f} h)" for p in stale])
    section("Variantes en vente sans ASIN ni référence d'un autre fournisseur", {p["handle"] for p, _ in no_asin})
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
        problems.append(f"{len(no_asin)} variantes en vente sans ASIN ni référence d'un autre fournisseur")
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
