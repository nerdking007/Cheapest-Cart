"""
Updates ONLY the Family column in prices.csv to more generic, natural
search terms (e.g. "Chicken Breast" -> family "Chicken", "Cinnamon Toast
Crunch" -> family "Cereal") — everything else in the file (Item names,
Default, Unit, and every store's real prices) is left exactly as-is.

This is a targeted, in-place edit rather than a full file replacement,
specifically so it's safe to run on your real, already-synced prices.csv
without losing any Kroger prices you've confirmed with kroger_sync.py.

USAGE:
    python3 update_families.py

Edit the FAMILY_UPDATES dictionary below if you want different generic
names than the defaults, or add entries for any items not listed here.
"""
import csv
import os

CSV_PATH = os.path.join(os.path.dirname(__file__), "prices.csv")

# item_name -> generic family name. Add/edit entries as you like.
FAMILY_UPDATES = {
    # Fruit
    "Apples, Gala": "Fruit",
    "Bananas": "Fruit",

    # Vegetables — deliberately broad: fresh, canned, and frozen all share
    # this family now, since typing "vegetables" safely shows every real
    # option instead of silently guessing one.
    "Bell Peppers": "Vegetables",
    "Onions": "Vegetables",
    "Potatoes": "Vegetables",
    "Lettuce": "Vegetables",
    "Canned Green Beans": "Vegetables",
    "Canned Tomatoes": "Vegetables",
    "Canned Carrots": "Vegetables",
    "Tomatoes, Beefsteak": "Vegetables",
    "Frozen Vegetables": "Vegetables",

    # Meat
    "Bacon, Thick": "Meat",
    "Chicken Breast": "Meat",
    "Ground Beef 93/7": "Meat",
    "Deli Ham": "Meat",

    # Dairy (Milk and Eggs kept separate — see below)
    "Butter, Sticks": "Dairy",
    "Shredded Cheese": "Dairy",
    "Yogurt, Greek": "Dairy",

    # Bakery
    "Bread, Honey Wheat": "Bakery",
    "Bagels": "Bakery",
    "Tortillas": "Bakery",

    # Grains
    "Pasta, Spaghetti": "Grains",
    "Rice, Jasmine": "Grains",

    # Baking
    "Flour": "Baking",
    "Sugar": "Baking",

    # Beverages
    "Coffee": "Beverages",
    "Orange Juice": "Beverages",

    # Frozen (meals/treats, not produce — Frozen Vegetables lives under
    # Vegetables above instead, since "what vegetable" matters more than
    # "what aisle" for search purposes)
    "Frozen Pizza": "Frozen",
    "Ice Cream Vanilla": "Frozen",

    # Left as their own specific families on purpose:
    # - Eggs: no other item fits naturally
    # - Cinnamon Toast Crunch (family "Cereal"): already generic, no change
    # - Peanut Butter: grouping under "Butter"/Dairy would be a confusing
    #   match (it's not a dairy product), so it stays standalone
    "Cinnamon Toast Crunch": "Cereal",

    # Milk variants already use family "Milk" and aren't touched here.
}


def update_families():
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    header = rows[0]
    expected = ["item", "family", "default", "unit"]
    if [h.strip().lower() for h in header[:4]] != expected:
        print(f"Expected header starting with {expected} — check prices.csv's format.")
        return

    changed = 0
    not_found = []
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        item_name = row[0].strip()
        if item_name in FAMILY_UPDATES:
            new_family = FAMILY_UPDATES[item_name]
            if row[1].strip() != new_family:
                row[1] = new_family
                changed += 1

    tracked_items = {row[0].strip() for row in rows[1:] if row and row[0].strip()}
    not_found = [name for name in FAMILY_UPDATES if name not in tracked_items]

    with open(CSV_PATH, "w", newline="") as f:
        csv.writer(f).writerows(rows)

    print(f"Updated {changed} family names in {os.path.basename(CSV_PATH)}.")
    if not_found:
        print(f"\nNote: these names in FAMILY_UPDATES weren't found in your CSV "
              f"(maybe renamed?): {', '.join(not_found)}")
    print("\nRun 'python3 import_prices.py' (or server_run.py) to apply this to the app.")


if __name__ == "__main__":
    update_families()
