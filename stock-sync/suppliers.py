#!/usr/bin/env python3
"""The sources other than Amazon.ae, recognised by the prefix of a SKU or of the variant metafield supplier.fallback:
"MEDX-<alias>" = MedX Pharmacy (medx.py), "PSAE-<handle>" = PadelShop.ae (padelshop.py).

Every source module has the same small interface: slug_of(sku), fetch(slug) -> page, sellable(page, on_sale), eta(),
STALE_HOURS, DUBAI_DAYS. Adding a source = one module + one line here.

Second source (Hoodo, 10 Nov: "si ils tombent en rupture padelshop est le second choix"): a variant whose SKU is an
Amazon.ae ASIN may carry supplier.fallback = "PSAE-<handle>" (or "MEDX-<alias>"). When Amazon.ae cannot sell it, the stock
sync keeps it on sale from that source, at that source's price, and remembers it in supplier.sync_state ("src").
"""
import medx
import padelshop

SOURCES = (("MedX", medx), ("PadelShop.ae", padelshop))


def module_of(sku):
    """(module, slug, display name) of a MEDX-/PSAE- reference, or (None, None, None)."""
    for name, mod in SOURCES:
        slug = mod.slug_of(sku)
        if slug:
            return mod, slug, name
    return None, None, None


def is_other_source(sku):
    """True for a SKU read by its own sync (not an Amazon.ae variant)."""
    return module_of(sku)[0] is not None
