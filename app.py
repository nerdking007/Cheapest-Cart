"""
Rough draft web UI (v1).

A single-page Flask app: type items into a list, submit, see the same
cheapest-store / cheapest-per-item comparison you already get from the CLI.

Run with: python3 app.py
Then open: http://127.0.0.1:5000 in your browser
"""
import difflib
from datetime import datetime

from flask import Flask, render_template, request

from db import get_connection
from compare import (
    cheapest_single_store,
    optimized_shopping_plan,
    get_price_at_store,
    get_stores_carrying_item,
    unit_label,
)

app = Flask(__name__)

FUZZY_MATCH_THRESHOLD = 0.6


def get_all_item_names():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM items ORDER BY name")
    names = [row["name"] for row in cur.fetchall()]
    conn.close()
    return names


def get_family_defaults():
    """
    Returns {family_lower: default_item_name} for every family that has a
    variant marked default — used only to VISUALLY highlight the typical
    pick in search results, not to silently choose for you anymore.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, family FROM items WHERE is_default = 1")
    rows = cur.fetchall()
    conn.close()
    return {(row["family"] or row["name"]).lower(): row["name"] for row in rows}


def get_family_members():
    """
    Returns {family_lower: [item_name, ...]} for every family. This is what
    matching actually uses: if a family has exactly one member, typing that
    family name is unambiguous and adds it directly. If a family groups
    several genuinely different items (e.g. "Canned Vegetables" covering
    canned green beans, tomatoes, and carrots), typing it is treated as
    ambiguous — you pick which one, instead of one getting silently chosen.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, family FROM items")
    rows = cur.fetchall()
    conn.close()
    members = {}
    for row in rows:
        family_key = (row["family"] or row["name"]).lower()
        members.setdefault(family_key, []).append(row["name"])
    return members


def get_item_families():
    """Returns {item_name: family} for every item — used by the search box's
    JS so typing a family name (even if it shares no text with the item's
    actual name) still surfaces every item in that family."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, family FROM items")
    rows = cur.fetchall()
    conn.close()
    return {row["name"]: (row["family"] or row["name"]) for row in rows}


def find_matching_item(user_input, all_items, family_members=None):
    """
    Matching, in order:
      0. Exact item name match (case-insensitive) — typing the full,
         specific name (e.g. "Milk (Half Gallon)") always wins outright.
      1. Exact FAMILY name match — if that family has exactly ONE item,
         resolves to it directly (no need to ask for something unambiguous).
         If the family has SEVERAL items (grouping genuinely different
         products, not just sizes), this is ambiguous — you're shown all
         of them rather than one getting silently guessed for you.
      2. Substring match against item names — "chick" -> "Chicken Breast".
      3. Fuzzy/typo match — asks "did you mean X?" for genuine misspellings.

    Returns a dict with a "type" of one of:
      "exact"     - matched cleanly, safe to add straight away
      "fuzzy"     - a guess only, needs the user to confirm or reject
      "ambiguous" - matched multiple items, needs a more specific word
      "none"      - no match at all
    """
    family_members = family_members or {}
    original = user_input.strip()
    user_input = original.lower()
    if not user_input:
        return {"type": "none", "word": original}

    for item in all_items:
        if item.lower() == user_input:
            return {"type": "exact", "word": original, "match": item}

    if user_input in family_members:
        members = family_members[user_input]
        if len(members) == 1:
            return {"type": "exact", "word": original, "match": members[0]}
        else:
            return {"type": "ambiguous", "word": original, "options": members}

    partial_matches = [item for item in all_items if user_input in item.lower()]
    if len(partial_matches) == 1:
        return {"type": "exact", "word": original, "match": partial_matches[0]}
    elif len(partial_matches) > 1:
        return {"type": "ambiguous", "word": original, "options": partial_matches}

    close_matches = difflib.get_close_matches(
        user_input, [i.lower() for i in all_items], n=1, cutoff=FUZZY_MATCH_THRESHOLD
    )
    if close_matches:
        guess = next(i for i in all_items if i.lower() == close_matches[0])
        return {"type": "fuzzy", "word": original, "guess": guess}

    return {"type": "none", "word": original}


def encode_list(items):
    """Encodes a list of item names into a single hidden-field-safe string."""
    return "|".join(items)


def parse_list(raw):
    """Reverses encode_list."""
    return [i for i in raw.split("|") if i] if raw else []


def encode_pending(pending_items):
    """Encodes pending fuzzy guesses as 'word=Guess|word2=Guess2' for a hidden field."""
    return "|".join(f"{p['word']}={p['guess']}" for p in pending_items)


def parse_pending(raw):
    """Reverses encode_pending back into a list of {'word':..., 'guess':...} dicts."""
    if not raw:
        return []
    pairs = [p for p in raw.split("|") if "=" in p]
    return [{"word": p.split("=", 1)[0], "guess": p.split("=", 1)[1]} for p in pairs]


def encode_purchased(purchased_items):
    """
    Encodes the purchase history log for a hidden field:
    'Milk::Aldi::3.15::Aug 31, 2026 02:15 PM|Eggs::Kroger::2.99::...'
    Uses '::' as the field separator since timestamps contain single colons.
    """
    return "|".join(
        f"{p['item']}::{p['store']}::{p['price']}::{p['timestamp']}"
        for p in purchased_items
    )


def parse_purchased(raw):
    """Reverses encode_purchased back into a list of purchase dicts."""
    if not raw:
        return []
    entries = []
    for chunk in raw.split("|"):
        if not chunk:
            continue
        parts = chunk.split("::")
        if len(parts) != 4:
            continue
        item, store, price, timestamp = parts
        entries.append({
            "item": item,
            "store": store,
            "price": float(price),
            "timestamp": timestamp,
        })
    return entries


DEFAULT_FILTERS = {"max_distance": None, "min_spend": 0.0, "min_items": 3}


def encode_filters(filters):
    """Encodes filter settings for a hidden field: 'max_distance=5|min_spend=0|min_items=3'."""
    max_distance = "" if filters["max_distance"] is None else filters["max_distance"]
    return f"max_distance={max_distance}|min_spend={filters['min_spend']}|min_items={filters['min_items']}"


def parse_filters(raw):
    """Reverses encode_filters, falling back to defaults for a first-time visit."""
    if not raw:
        return dict(DEFAULT_FILTERS)
    values = dict(DEFAULT_FILTERS)
    for chunk in raw.split("|"):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        if key == "max_distance":
            values["max_distance"] = float(value) if value else None
        elif key == "min_spend":
            values["min_spend"] = float(value) if value else 0.0
        elif key == "min_items":
            values["min_items"] = int(float(value)) if value else 0
    return values


@app.route("/", methods=["GET", "POST"])
def index():
    all_items = get_all_item_names()
    family_defaults = get_family_defaults()
    family_members = get_family_members()
    item_families = get_item_families()
    warnings = []
    single_store_results = None
    plan = None
    item_options = {}

    # The cart, pending guesses, purchase history, and filter settings all
    # persist across submits via hidden form fields, since Flask itself
    # doesn't remember anything between requests.
    grocery_list = parse_list(request.form.get("cart", ""))
    pending = parse_pending(request.form.get("pending", ""))
    purchased = parse_purchased(request.form.get("purchased", ""))
    filters = parse_filters(request.form.get("filters", ""))
    view = request.form.get("view", "cart")

    # The browser fills these in automatically via the Geolocation API
    # (see the JS in index.html) — they may be missing/blank if the user
    # denied the location permission or their browser doesn't support it.
    user_lat = request.form.get("user_lat", "")
    user_lon = request.form.get("user_lon", "")
    user_lat = float(user_lat) if user_lat else None
    user_lon = float(user_lon) if user_lon else None

    action = request.form.get("action")

    if action == "clear":
        grocery_list = []
        pending = []

    elif action == "show_history":
        view = "history"

    elif action == "show_cart":
        view = "cart"

    elif action == "show_filters":
        view = "filters"

    elif action == "save_filters":
        raw_max_distance = request.form.get("filter_max_distance", "").strip()
        raw_min_spend = request.form.get("filter_min_spend", "").strip()
        raw_min_items = request.form.get("filter_min_items", "").strip()
        filters = {
            "max_distance": float(raw_max_distance) if raw_max_distance else None,
            "min_spend": float(raw_min_spend) if raw_min_spend else 0.0,
            "min_items": int(raw_min_items) if raw_min_items else 0,
        }
        view = "cart"

    elif action == "resolve":
        resolve_word = request.form.get("resolve_word", "")
        resolve_guess = request.form.get("resolve_guess", "")
        resolve_decision = request.form.get("resolve_decision")

        # Remove this word from the pending list either way — it's resolved now
        pending = [p for p in pending if p["word"] != resolve_word]

        if resolve_decision == "yes" and resolve_guess not in grocery_list:
            grocery_list.append(resolve_guess)

    elif action == "add":
        raw_text = request.form.get("items", "")
        # One item per LINE, not comma-separated — a lot of item names use
        # a comma as part of the name itself (e.g. "Milk, Whole (Gallon)",
        # "Tomatoes, Beefsteak"), so splitting on commas would chop a single
        # item name into two bogus fragments. Newlines are unambiguous.
        typed_items = [line.strip() for line in raw_text.split("\n") if line.strip()]

        for typed in typed_items:
            result = find_matching_item(typed, all_items, family_members)

            if result["type"] == "exact":
                if result["match"] not in grocery_list:
                    grocery_list.append(result["match"])
            elif result["type"] == "fuzzy":
                if result["word"] not in [p["word"] for p in pending]:
                    pending.append(result)
            elif result["type"] == "ambiguous":
                warnings.append(
                    f"'{result['word']}' matches multiple items: "
                    f"{', '.join(result['options'])} — please be more specific."
                )
            else:
                warnings.append(f"No item found matching '{result['word']}'")

    elif action == "remove_item":
        # A plain "changed my mind" removal — does NOT get logged as a
        # purchase, since it never actually happened.
        item_name = request.form.get("item_name")
        if item_name in grocery_list:
            grocery_list.remove(item_name)

    elif action == "buy_item":
        # A real purchase event — logs which store it actually came from,
        # which may differ from the cheapest recommendation.
        item_name = request.form.get("item_name")
        chosen_store = request.form.get("chosen_store")
        if item_name in grocery_list and chosen_store:
            info = get_price_at_store(item_name, chosen_store)
            if info is not None:
                purchased.append({
                    "item": item_name,
                    "store": chosen_store,
                    "price": info["price"],
                    "timestamp": datetime.now().strftime("%b %d, %Y %I:%M %p"),
                })
                grocery_list.remove(item_name)
            else:
                warnings.append(f"{chosen_store} doesn't have a price on file for {item_name}.")

    elif action == "buy_all":
        # Bulk "I bought everything" — uses the SAME filtered recommendation
        # shown on screen (respecting max distance / min spend / min items),
        # not just the raw cheapest price, so it matches what you saw.
        if grocery_list:
            plan = optimized_shopping_plan(
                grocery_list, user_lat, user_lon,
                filters["max_distance"], filters["min_spend"], filters["min_items"],
            )
            for item, info in plan["assignment"].items():
                purchased.append({
                    "item": item,
                    "store": info["store"],
                    "price": info["price"],
                    "timestamp": datetime.now().strftime("%b %d, %Y %I:%M %p"),
                })
            for item in plan["dropped_items"]:
                warnings.append(f"Skipped '{item}' — no store within your filters carries it.")
            grocery_list = list(plan["dropped_items"])

    if grocery_list:
        single_store_results = cheapest_single_store(
            grocery_list, user_lat, user_lon, filters["max_distance"]
        )
        plan = optimized_shopping_plan(
            grocery_list, user_lat, user_lon,
            filters["max_distance"], filters["min_spend"], filters["min_items"],
        )
        for item in grocery_list:
            item_options[item] = get_stores_carrying_item(item)

    return render_template(
        "index.html",
        all_items=all_items,
        family_defaults=family_defaults,
        item_families=item_families,
        grocery_list=grocery_list,
        warnings=warnings,
        pending=pending,
        purchased=purchased,
        filters=filters,
        view=view,
        item_options=item_options,
        unit_label=unit_label,
        cart_field=encode_list(grocery_list),
        pending_field=encode_pending(pending),
        purchased_field=encode_purchased(purchased),
        filters_field=encode_filters(filters),
        user_lat=user_lat,
        user_lon=user_lon,
        single_store_results=single_store_results,
        plan=plan,
    )


if __name__ == "__main__":
    app.run(debug=True)
