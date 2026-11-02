"""Brand-interleaving order for a product list (pure functions, no Shopify calls).

A product is a dict: id, brand, type, line, band (price band 0..3), pop (0 = regular, 1 = best-seller or
incontournable, 2 = both), key (stable tie-break string).

build(products)   -> full order from scratch: position by position, greedy, with look-back penalties.
insert(placed, new) -> slot new products into an existing order without moving the others.
metrics(order)    -> numbers used in the run report.
"""
import hashlib

BRAND_W = [0, 120, 80, 55, 35, 20, 10]   # penalty when the same brand is `distance` places back (index = distance)
TYPE_W = [0, 20, 12, 6]
LINE_W = [0, 25, 12, 6]                  # same product line (first two words after the brand)
BRAND_URGENCY = 100.0                    # pulls brands with many products left to be spread, not left for the tail
TYPE_URGENCY = 40.0
WIDE_BRAND_W = 5.0                       # same brand 7 to 12 places back: still a bit too close
PAGE = 24                                # the storefront shows 24 products per page: a brand appears once per page 1
POP_BONUS = 18.0                         # best-sellers come earlier, but never at the cost of a brand block


def _noise(key):
    return int(hashlib.sha1(key.encode()).hexdigest()[:6], 16) / 0xFFFFFF  # 0..1, stable


def _back_penalty(p, order, scale_gap=None):
    """Penalty of putting p right after `order` (list of products)."""
    pen = 0.0
    n = len(order)
    for k in range(1, len(BRAND_W)):
        if k > n:
            break
        q = order[n - k]
        if q["brand"] == p["brand"]:
            w = BRAND_W[k]
            if scale_gap is not None and k >= scale_gap:
                w *= 0.25  # a brand that owns most of what is left cannot be spread any wider
            pen += w
        if k < len(TYPE_W) and q["type"] == p["type"]:
            pen += TYPE_W[k]
        if k < len(LINE_W) and q["line"] and q["line"] == p["line"]:
            pen += LINE_W[k]
    for k in range(len(BRAND_W), 13):
        if k <= n and order[n - k]["brand"] == p["brand"]:
            pen += WIDE_BRAND_W
    if n < PAGE and any(q["brand"] == p["brand"] for q in order[:n]):
        pen += 25
    if n >= 1 and order[-1]["band"] == p["band"]:
        pen += 6
        if n >= 2 and order[-2]["band"] == p["band"]:
            pen += 6
    return pen


def build(products):
    left = sorted(products, key=lambda p: p["key"])
    order = []
    total = len(left)
    brand_left, type_left = {}, {}
    for p in left:
        brand_left[p["brand"]] = brand_left.get(p["brand"], 0) + 1
        type_left[p["type"]] = type_left.get(p["type"], 0) + 1
    while left:
        remaining = len(left)
        pos = total - remaining
        front = 1.0 - 0.7 * pos / max(total, 1)
        best, best_score = None, None
        for p in left:
            gap = remaining / brand_left[p["brand"]]
            score = (-_back_penalty(p, order, gap)
                     + BRAND_URGENCY * brand_left[p["brand"]] / remaining
                     + TYPE_URGENCY * type_left[p["type"]] / remaining
                     + POP_BONUS * p["pop"] * front / 2
                     + _noise(p["key"]))
            if best_score is None or score > best_score:
                best, best_score = p, score
        left.remove(best)
        order.append(best)
        brand_left[best["brand"]] -= 1
        type_left[best["type"]] -= 1
    return order


def _slot_cost(p, order, i):
    """Cost of putting p at index i of order (looking at neighbours on both sides)."""
    cost = 0.0
    for k in range(1, len(BRAND_W)):
        for j in (i - k, i + k - 1):
            if 0 <= j < len(order):
                q = order[j]
                if q["brand"] == p["brand"]:
                    cost += BRAND_W[k]
                if k < len(TYPE_W) and q["type"] == p["type"]:
                    cost += TYPE_W[k]
                if k < len(LINE_W) and q["line"] and q["line"] == p["line"]:
                    cost += LINE_W[k]
    return cost


def insert(placed, new):
    """Slot `new` products into `placed` (kept in their order). Most popular first; each goes to the cheapest
    slot, a stable hash decides between equal slots so a batch of one brand spreads over the whole list."""
    order = list(placed)
    for p in sorted(new, key=lambda p: (-p["pop"], p["key"])):
        n = len(order)
        target = _noise(p["key"])
        if p["pop"]:
            target *= 0.5  # popular products land in the first half
        best_i, best = 0, None
        for i in range(n + 1):
            c = _slot_cost(p, order, i) + 3.0 * abs(i / max(n, 1) - target)
            if best is None or c < best:
                best_i, best = i, c
        order.insert(best_i, p)
    return order


def metrics(order, page=PAGE):
    """Adjacent same-brand pairs, same brand twice within 4, longest brand run, longest type run, and the
    number of different brands in the first page."""
    adj = within4 = brand_run = type_run = 0
    run_b = run_t = 0
    for i, p in enumerate(order):
        if i and order[i - 1]["brand"] == p["brand"]:
            adj += 1
            run_b += 1
        else:
            run_b = 1
        if i and order[i - 1]["type"] == p["type"]:
            run_t += 1
        else:
            run_t = 1
        brand_run, type_run = max(brand_run, run_b), max(type_run, run_t)
        if any(order[j]["brand"] == p["brand"] for j in range(max(0, i - 4), i)):
            within4 += 1
    first = order[:page]
    return {"n": len(order), "adjacent_same_brand": adj, "same_brand_within_4": within4,
            "longest_brand_run": brand_run, "longest_type_run": type_run,
            "brands_on_first_page": len({p["brand"] for p in first}), "first_page_size": len(first)}
