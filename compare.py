"""
Core comparison logic (v1 scope):
  1. Given a grocery list, compute the total cost at each store.
  2. Report the cheapest single store to buy everything from.
  3. Also show the cheapest-per-item split, for comparison.

Missing items at a store are excluded from that store's total but flagged,
since a store missing half your list shouldn't "win" on a technicality.
"""
from db import get_connection
from distance import haversine_distance_miles


def get_store_locations():
    """Returns {store_name: (latitude, longitude)} for every store that has coordinates set."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, latitude, longitude FROM stores WHERE latitude IS NOT NULL")
    rows = cur.fetchall()
    conn.close()
    return {row["name"]: (row["latitude"], row["longitude"]) for row in rows}


def get_prices_for_list(item_names):
    """
    Returns a dict: {store_name: {item_name: price}} for every store that
    carries at least one of the requested items.
    """
    conn = get_connection()
    cur = conn.cursor()

    placeholders = ",".join("?" for _ in item_names)
    cur.execute(
        f"""
        SELECT s.name AS store_name, i.name AS item_name, p.price
        FROM prices p
        JOIN stores s ON s.id = p.store_id
        JOIN items i ON i.id = p.item_id
        WHERE i.name IN ({placeholders})
        """,
        item_names,
    )
    rows = cur.fetchall()
    conn.close()

    results = {}
    for row in rows:
        results.setdefault(row["store_name"], {})[row["item_name"]] = row["price"]
    return results


def get_price_at_store(item_name, store_name):
    """Returns the price of a single item at a single store, or None if not carried there."""
    data = get_prices_for_list([item_name])
    return data.get(store_name, {}).get(item_name)


def get_stores_carrying_item(item_name):
    """Returns [(store_name, price), ...] for every store that carries this item, cheapest first."""
    data = get_prices_for_list([item_name])
    options = [
        (store_name, prices[item_name])
        for store_name, prices in data.items()
        if item_name in prices
    ]
    options.sort(key=lambda pair: pair[1])
    return options


def cheapest_single_store(item_names, user_lat=None, user_lon=None, max_distance=None):
    """
    Ranks stores by total cost for the FULL list. Stores missing items
    are still shown, but flagged with what they're missing so an
    incomplete-but-cheap total doesn't look misleadingly good.

    If user_lat/user_lon are given, adds a straight-line "distance_miles"
    to each result (None if that store has no coordinates on file).

    If max_distance is given (and a store's distance is known), stores
    farther away than that are left out entirely.
    """
    data = get_prices_for_list(item_names)
    locations = get_store_locations() if user_lat is not None else {}
    results = []

    for store_name, item_prices in data.items():
        distance = None
        if user_lat is not None and store_name in locations:
            store_lat, store_lon = locations[store_name]
            distance = haversine_distance_miles(user_lat, user_lon, store_lat, store_lon)

        if max_distance is not None and distance is not None and distance > max_distance:
            continue  # too far — leave it out of consideration entirely

        found_items = set(item_prices.keys())
        missing = [i for i in item_names if i not in found_items]
        total = round(sum(item_prices.values()), 2)

        results.append({
            "store": store_name,
            "total": total,
            "items_found": len(found_items),
            "items_missing": missing,
            "distance_miles": distance,
        })

    # Sort by: fewest missing items first, then by total price
    results.sort(key=lambda r: (len(r["items_missing"]), r["total"]))
    return results

def unit_label(unit):
    """Turns an internal unit code into a human-friendly display label."""
    return {
        "oz": "oz",
        "fl_oz": "fl oz",
        "count": "each",
    }.get(unit, unit)

def cheapest_per_item(item_names):
    """
    For each item, finds which store has the lowest price.
    Returns a dict: {item_name: {"store": ..., "price": ...}}
    plus the combined total if you split your shopping this way.
    """
    data = get_prices_for_list(item_names)
    best_per_item = {}

    for item in item_names:
        best_store, best_price = None, None
        for store_name, item_prices in data.items():
            if item in item_prices:
                if best_price is None or item_prices[item] < best_price:
                    best_price = item_prices[item]
                    best_store = store_name
        best_per_item[item] = {"store": best_store, "price": best_price}

    total = round(sum(
        v["price"] for v in best_per_item.values() if v["price"] is not None
    ), 2)
    stores_needed = sorted({
        v["store"] for v in best_per_item.values() if v["store"] is not None
    })

    return {"per_item": best_per_item, "total": total, "stores_needed": stores_needed}


def optimized_shopping_plan(item_names, user_lat=None, user_lon=None,
                              max_distance=None, min_spend=0, min_items=3):
    """
    Decides which combination of stores to actually shop at, respecting
    three filters:
      - max_distance: stores farther than this (straight-line) are left
        out of consideration entirely.
      - min_spend: a store isn't "worth the stop" unless your total spend
        there reaches at least this much.
      - min_items: a store isn't "worth the stop" unless you're buying at
        least this many items there.

    Starts from a plain cheapest-per-item assignment, then repeatedly
    checks for any store that falls short of min_spend/min_items. If that
    store's items ALL have another allowed store that also carries them,
    the store gets dropped and its items reassigned to their next-best
    option. If a store is the ONLY place that carries one of its assigned
    items, it's kept anyway (flagged as "kept out of necessity") — you
    can't buy an item nowhere just because a filter says so.

    Returns a dict:
      "assignment": {item: {"store":..., "price":...}} — final per-item pick
      "dropped_items": items no allowed store carries at all
      "stores_used": [{"store", "item_count", "total", "distance_miles",
                        "meets_minimums"}, ...], sorted nearest-first
      "total_cost": sum of the final assignment
    """
    data = get_prices_for_list(item_names)
    locations = get_store_locations()

    store_distance = {}
    for store_name in data:
        if user_lat is not None and store_name in locations:
            lat, lon = locations[store_name]
            store_distance[store_name] = haversine_distance_miles(user_lat, user_lon, lat, lon)
        else:
            store_distance[store_name] = None  # unknown — don't penalize for it

    def distance_ok(store_name):
        if max_distance is None:
            return True
        d = store_distance.get(store_name)
        return True if d is None else d <= max_distance

    allowed = {s for s in data if distance_ok(s)}

    def build_assignment(allowed_set):
        assignment = {}
        dropped = []
        for item in item_names:
            best_store, best_price = None, None
            for store in allowed_set:
                price = data.get(store, {}).get(item)
                if price is not None and (best_price is None or price < best_price):
                    best_store, best_price = store, price
            if best_store:
                assignment[item] = {"store": best_store, "price": best_price}
            else:
                dropped.append(item)
        return assignment, dropped

    def compute_stats(assignment):
        stats = {}
        for item, info in assignment.items():
            s = stats.setdefault(info["store"], {"items": 0, "total": 0.0})
            s["items"] += 1
            s["total"] += info["price"]
        return stats

    # Iteratively drop stores that fall short of the minimums, as long as
    # doing so doesn't strand an item with nowhere else to be bought.
    for _ in range(len(allowed) + 1):
        assignment, dropped = build_assignment(allowed)
        stats = compute_stats(assignment)

        weak_stores = [
            s for s, st in stats.items()
            if st["items"] < min_items or st["total"] < min_spend
        ]
        if not weak_stores:
            break

        # Try the weakest stores first (fewest items, then lowest total)
        weak_stores.sort(key=lambda s: (stats[s]["items"], stats[s]["total"]))

        droppable = None
        for candidate in weak_stores:
            items_here = [item for item, info in assignment.items() if info["store"] == candidate]
            has_alternative_for_all = all(
                any(other != candidate and item in data.get(other, {}) for other in allowed)
                for item in items_here
            )
            if has_alternative_for_all:
                droppable = candidate
                break

        if droppable is None:
            break  # every weak store is essential for at least one item — stop here

        allowed.discard(droppable)

    assignment, dropped = build_assignment(allowed)
    stats = compute_stats(assignment)

    stores_used = []
    for store, st in stats.items():
        stores_used.append({
            "store": store,
            "item_count": st["items"],
            "total": round(st["total"], 2),
            "distance_miles": store_distance.get(store),
            "meets_minimums": st["items"] >= min_items and st["total"] >= min_spend,
        })
    stores_used.sort(key=lambda s: (s["distance_miles"] is None, s["distance_miles"] or 0))

    total_cost = round(sum(info["price"] for info in assignment.values()), 2)

    return {
        "assignment": assignment,
        "dropped_items": dropped,
        "stores_used": stores_used,
        "total_cost": total_cost,
    }
    print(f"\nGrocery list: {', '.join(item_names)}")
    print("=" * 50)

    print("\n-- Cheapest single store (buy everything there) --")
    for r in cheapest_single_store(item_names, user_lat, user_lon):
        flag = f"  (missing: {', '.join(r['items_missing'])})" if r["items_missing"] else ""
        dist = f"  [{r['distance_miles']} mi]" if r["distance_miles"] is not None else ""
        print(f"  {r['store']:<24} ${r['total']:>6.2f}{dist}{flag}")

    print("\n-- Cheapest per item (split across stores) --")
    split = cheapest_per_item(item_names)
    for item, info in split["per_item"].items():
        if info["store"]:
            print(f"  {item:<16} ${info['price']:.2f} @ {info['store']}")
        else:
            print(f"  {item:<16} not found at any tracked store")
    print(f"\n  Split total: ${split['total']:.2f}  "
          f"(requires visiting: {', '.join(split['stores_needed'])})")


if __name__ == "__main__":
    sample_list = ["Milk", "Eggs", "Bread", "Bananas", "Chicken Breast"]
    print_report(sample_list)
