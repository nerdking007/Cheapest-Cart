"""
Loads price data from a spreadsheet-style CSV into the database.

Expected layout (open/edit this in Excel, Google Sheets, or any text editor):

    Item,Family,Default,Unit,Walmart,Aldi,Kroger,Price Chopper
    Milk (Half Gallon),Milk,no,fl_oz,2.29@64,1.99@64,,
    Milk (Gallon),Milk,yes,fl_oz,3.48@128,3.15@128,3.69@128,3.59@128
    Eggs,Eggs,yes,count,2.98@12,2.65@12,3.19@12,2.89@12
    Chicken Breast,Chicken Breast,yes,oz,3.24@48,,2.99@48,3.10@48

- Item: the exact, specific name for this size/variant (what shows up in
  the cart once picked).
- Family: the general name people would actually type to search for it
  (e.g. both milk rows share Family "Milk"). For an item with only one
  size, Family is usually just the same as Item.
- Default: "yes" for the ONE variant in a family that should be picked
  automatically when someone types the family name and hits enter without
  choosing a specific size (e.g. a gallon of milk, a dozen eggs — whatever
  most people mean by that word). Every other variant in that family
  should be "no". A family with only one item is always "yes".
- Unit: one of oz, fl_oz, count (oz = weight, fl_oz = volume/liquid,
  count = discrete items like eggs) — stays the same across a family's
  variants and across every store.
- Every column after Unit: a store name.
- Each filled cell: price@quantity — e.g. "3.15@128" means $3.15 for
  128 fl oz. Leave a cell BLANK if a store doesn't carry that item.

To update prices: edit prices.csv, save/export as CSV (not .xlsx), then:
    python3 import_prices.py
"""
import csv
import os

from db import get_connection, init_db

CSV_PATH = os.path.join(os.path.dirname(__file__), "prices.csv")
VALID_UNITS = {"oz", "fl_oz", "count"}


def import_prices(csv_path=CSV_PATH):
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    # prices.csv is the single source of truth — wipe existing prices AND
    # items first, so a row you've since deleted from the CSV actually
    # disappears from the app, instead of lingering forever as a "ghost"
    # item that still shows up in search with no current price on it.
    cur.execute("DELETE FROM prices")
    cur.execute("DELETE FROM items")

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)

        expected = ["item", "family", "default", "unit"]
        header_check = [h.strip().lower() for h in header[:4]]
        if len(header) < 5 or header_check != expected:
            print("Expected header like: Item,Family,Default,Unit,Walmart,Aldi,... "
                  f"(first four columns must be {expected})")
            return

        store_names = [name.strip() for name in header[4:] if name.strip()]

        if not store_names:
            print("No store columns found — check your CSV header row.")
            return

        store_ids = {}
        for store_name in store_names:
            cur.execute("INSERT OR IGNORE INTO stores (name) VALUES (?)", (store_name,))
            cur.execute("SELECT id FROM stores WHERE name = ?", (store_name,))
            store_ids[store_name] = cur.fetchone()["id"]

        items_seen = 0
        prices_seen = 0

        for row in reader:
            if not row or not row[0].strip():
                continue  # skip blank rows

            item_name = row[0].strip()
            family = row[1].strip() if len(row) > 1 and row[1].strip() else item_name
            is_default_raw = row[2].strip().lower() if len(row) > 2 else "yes"
            is_default = 1 if is_default_raw in ("yes", "y", "true", "1") else 0
            unit_type = row[3].strip().lower() if len(row) > 3 else ""

            if unit_type not in VALID_UNITS:
                print(f"  Skipping '{item_name}': unit must be one of "
                      f"{sorted(VALID_UNITS)}, got '{unit_type}'")
                continue

            cur.execute(
                "INSERT OR IGNORE INTO items (name, unit_type, family, is_default) VALUES (?, ?, ?, ?)",
                (item_name, unit_type, family, is_default),
            )
            cur.execute(
                "UPDATE items SET unit_type = ?, family = ?, is_default = ? WHERE name = ?",
                (unit_type, family, is_default, item_name),
            )
            cur.execute("SELECT id FROM items WHERE name = ?", (item_name,))
            item_id = cur.fetchone()["id"]
            items_seen += 1

            for i, store_name in enumerate(store_names):
                cell = row[i + 4].strip() if i + 4 < len(row) else ""

                if not cell:
                    continue  # blank cell = this store doesn't carry the item

                if "@" not in cell:
                    print(f"  Skipping '{item_name}' at '{store_name}': "
                          f"expected 'price@quantity', got '{cell}'")
                    continue

                price_str, qty_str = cell.split("@", 1)
                try:
                    price = float(price_str)
                    quantity = float(qty_str)
                except ValueError:
                    print(f"  Skipping '{item_name}' at '{store_name}': "
                          f"'{cell}' isn't a valid price@quantity")
                    continue

                if quantity <= 0:
                    print(f"  Skipping '{item_name}' at '{store_name}': "
                          f"quantity must be greater than 0")
                    continue

                cur.execute(
                    """INSERT INTO prices (store_id, item_id, price, quantity)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(store_id, item_id) DO UPDATE SET
                           price = excluded.price,
                           quantity = excluded.quantity,
                           last_updated = datetime('now')""",
                    (store_ids[store_name], item_id, price, quantity),
                )
                prices_seen += 1

    conn.commit()
    conn.close()
    print(f"Imported {items_seen} items across {len(store_names)} stores "
          f"({prices_seen} prices) from {os.path.basename(csv_path)}")


if __name__ == "__main__":
    import_prices()
