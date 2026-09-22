"""
Browse Kroger's catalog by search term and add brand-new tracked items to
prices.csv — for expanding what you track, not just refreshing what's
already there (that's kroger_sync.py's job).

HONEST SCOPE: this does NOT pull "everything in the store." A single
Kroger's catalog has tens of thousands of SKUs, most of which (cleaning
supplies, random one-off brands, etc.) wouldn't be useful staples to
track, and couldn't even be compared since no other store would have a
matching entry. This is a targeted, term-by-term browse instead — search
"cereal", pick the ones you actually want tracked, repeat for other
categories as needed.

USAGE:
    python3 kroger_discover.py

For each new item you add, you confirm/adjust:
  - The item name that'll show up in your app
  - Its Family (for size-variant grouping — see the earlier "milk" example)
  - Whether it's the Default variant for that family
  - Its Unit type (oz / fl_oz / count)
Kroger's own price and package size fill in automatically, and this item
gets immediately linked in kroger_mapping.csv, so future kroger_sync.py
runs pull it directly without needing to re-search.
"""
import csv
import os

from kroger_common import (
    get_access_token, get_credentials_or_exit, find_store_location,
    search_by_term, parse_size_to_quantity, load_mapping, save_mapping,
    CSV_PATH, ZIP_CODE,
)

VALID_UNITS = {"oz", "fl_oz", "count"}


def prompt_unit_type(suggested):
    """Asks the user to confirm/override the guessed unit type."""
    while True:
        raw = input(f"  Unit type (oz / fl_oz / count) [{suggested}]: ").strip().lower()
        if not raw:
            return suggested
        if raw in VALID_UNITS:
            return raw
        print(f"  Please enter one of: {', '.join(sorted(VALID_UNITS))}")


def guess_unit_type(sold_by, size_text):
    """
    A starting guess only — always shown to the user to confirm, never
    applied silently. Checks the actual size text FIRST (e.g. "19.1 oz"
    clearly means oz), since soldBy describes how it's rung up at
    checkout (by weight vs. by unit), not what the package size is
    measured in — a cereal box is soldBy="unit" but still sized in oz.
    """
    text = (size_text or "").lower()
    if any(word in text for word in ("gal", "fl oz", "quart", "qt", "liter", "ml")):
        return "fl_oz"
    if "oz" in text or "lb" in text or "pound" in text:
        return "oz"
    if "ct" in text or "count" in text or " ea" in text or text.endswith("ea"):
        return "count"
    # No usable size text — fall back to soldBy as a last resort
    return "oz" if sold_by == "weight" else "count"


def add_one_item(product, header, kroger_col, existing_item_names, mapping, rows, interactive=True):
    """
    Turns one Kroger product into a new prices.csv row.
    interactive=True: asks you to confirm/adjust name, family, default, unit.
    interactive=False (used by "add all"): auto-accepts sensible guesses —
    Kroger's own product name, its own standalone family, and a guessed
    unit type — trading a little precision for speed. You can always fix
    up Family groupings afterward with update_families.py.
    Returns True if added, False if skipped.
    """
    items = product.get("items", [])
    if not items or items[0].get("price", {}).get("regular") is None:
        print(f"  Skipping '{product.get('description')}' — no price available.")
        return False

    price = items[0]["price"]["regular"]
    size_text = items[0].get("size", "")
    sold_by = items[0].get("soldBy", "")
    suggested_name = product.get("description", "Unnamed item").strip()

    if interactive:
        print(f"\nAdding: {suggested_name}")
        item_name = input(f"  Item name [{suggested_name}]: ").strip() or suggested_name
    else:
        item_name = suggested_name

    if item_name in existing_item_names:
        print(f"  '{item_name}' already exists in prices.csv — "
              f"skipping (use kroger_sync.py to refresh its price instead).")
        return False

    guessed_unit = guess_unit_type(sold_by, size_text)

    if interactive:
        family = input(f"  Family (for grouping size variants) [{item_name}]: ").strip() or item_name
        is_default = input("  Is this the default size for its family? (Y/n): ").strip().lower()
        is_default = "no" if is_default == "n" else "yes"
        print(f"  Kroger lists this as: size='{size_text}', soldBy='{sold_by}'")
        unit_type = prompt_unit_type(guessed_unit)
    else:
        family = item_name  # its own standalone family — safe default, no collision risk
        is_default = "yes"
        unit_type = guessed_unit

    quantity = parse_size_to_quantity(size_text, unit_type)
    if quantity is None:
        if interactive:
            manual = input(f"  Couldn't parse size '{size_text}' as {unit_type} — "
                            f"enter quantity manually: ").strip()
            try:
                quantity = float(manual)
            except ValueError:
                print("  Invalid number, skipping this item.")
                return False
        else:
            print(f"  Skipping '{item_name}' — couldn't parse size '{size_text}' "
                  f"as {unit_type} (add it manually with kroger_sync.py or -i instead).")
            return False

    new_row = [""] * len(header)
    new_row[0] = item_name
    new_row[1] = family
    new_row[2] = is_default
    new_row[3] = unit_type
    new_row[kroger_col] = f"{price}@{quantity:g}"
    rows.append(new_row)
    existing_item_names.add(item_name)
    mapping[item_name] = product["productId"]

    print(f"  Added '{item_name}' — Kroger: {price}@{quantity:g}")
    return True


def get_existing_families(rows):
    """Returns a sorted list of distinct Family names already in prices.csv."""
    families = {
        row[1].strip() for row in rows[1:]
        if row and len(row) > 1 and row[1].strip()
    }
    return sorted(families)


def run_search_and_add(term, token, location_id, header, kroger_col,
                        existing_item_names, mapping, rows):
    """
    One full search-and-choose cycle for a single term: searches Kroger,
    shows results, and lets you pick which to add (numbers, 'all', or
    blank to skip this term). Used both for a one-off manual search and
    for each step of the "search every existing family" loop.
    """
    if len(term) < 3:
        print(f"Skipping '{term}' — search terms need at least 3 characters.")
        return

    all_results = search_by_term(token, location_id, term, limit=25)
    if not all_results:
        print(f"No results found for '{term}'.")
        return

    # Hide anything whose name is already tracked, so repeat searches (e.g.
    # re-running the same family later to look for new items) only show
    # candidates you don't have yet, instead of the same list every time.
    results = [
        p for p in all_results
        if p.get("description", "Unnamed item").strip() not in existing_item_names
    ]
    hidden_count = len(all_results) - len(results)

    if not results:
        note = f" ({hidden_count} already tracked, hidden)" if hidden_count else ""
        print(f"No new results for '{term}'{note}.")
        return

    print(f"\nResults for '{term}':", end="")
    if hidden_count:
        print(f" ({hidden_count} already-tracked item{'s' if hidden_count != 1 else ''} hidden)")
    else:
        print()
    for i, product in enumerate(results):
        desc = product.get("description", "Unknown")
        items = product.get("items", [])
        price = items[0].get("price", {}).get("regular") if items else None
        size = items[0].get("size", "") if items else ""
        print(f"  {i + 1}. {desc} — {size} — "
              f"{'$' + str(price) if price else 'no price available'}")

    choices = input(
        "\nWhich should be added as new tracked items? "
        "(comma-separated numbers, 'all' to add everything shown, "
        "or blank to skip): "
    ).strip()
    if not choices:
        return

    if choices.lower() == "all":
        print(f"\nAdding all {len(results)} results using auto-guessed "
              f"name/family/unit (no per-item confirmation)...")
        added = 0
        for product in results:
            if add_one_item(product, header, kroger_col, existing_item_names,
                             mapping, rows, interactive=False):
                added += 1
        with open(CSV_PATH, "w", newline="") as f:
            csv.writer(f).writerows(rows)
        save_mapping(mapping)
        print(f"Added {added} of {len(results)} items.")
        return

    for choice in choices.split(","):
        choice = choice.strip()
        try:
            product = results[int(choice) - 1]
        except (ValueError, IndexError):
            print(f"  Skipping invalid choice '{choice}'.")
            continue

        if add_one_item(product, header, kroger_col, existing_item_names,
                         mapping, rows, interactive=True):
            with open(CSV_PATH, "w", newline="") as f:
                csv.writer(f).writerows(rows)
            save_mapping(mapping)


def discover():
    client_id, client_secret = get_credentials_or_exit()

    print("Getting access token...")
    token = get_access_token(client_id, client_secret)

    location_id, _, _ = find_store_location(token, ZIP_CODE)
    print(f"Using Kroger location: {location_id}")

    mapping = load_mapping()

    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    existing_item_names = {row[0].strip() for row in rows[1:] if row and row[0].strip()}

    if "Kroger" not in header:
        print("Couldn't find a 'Kroger' column in prices.csv.")
        return
    kroger_col = header.index("Kroger")

    while True:
        term = input(
            "\nSearch Kroger for (blank to quit, or type 'family' to search "
            "one of your existing categories instead): "
        ).strip()
        if not term:
            break

        if term.lower() == "family":
            families = get_existing_families(rows)
            if not families:
                print("No families found in prices.csv yet.")
                continue

            print("\nYour existing families:")
            for i, fam in enumerate(families):
                print(f"  {i + 1}. {fam}")

            fam_choice = input(
                "Which one should Kroger be searched for? "
                "(number, or 'all' to go through every family one by one): "
            ).strip()

            if fam_choice.lower() == "all":
                print(f"\nGoing through all {len(families)} families one at a time — "
                      f"for each, pick what to add (or leave blank to skip to the next).")
                for i, fam in enumerate(families):
                    print(f"\n=== Family {i + 1}/{len(families)}: {fam} ===")
                    run_search_and_add(fam, token, location_id, header, kroger_col,
                                        existing_item_names, mapping, rows)
                print("\nFinished going through all families.")
                continue

            try:
                term = families[int(fam_choice) - 1]
            except (ValueError, IndexError):
                print("Invalid choice.")
                continue
            print(f"Searching Kroger for: {term}")

        run_search_and_add(term, token, location_id, header, kroger_col,
                            existing_item_names, mapping, rows)

    print(f"\nDone. Run 'python3 import_prices.py' (or server_run.py) to load new items into the app.")
    print("New items only have a Kroger price so far — fill in the other stores' "
          "columns in prices.csv by hand when you get a chance.")


if __name__ == "__main__":
    discover()
