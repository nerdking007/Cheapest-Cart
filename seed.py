"""
Populates the database with sample stores/items/prices so you have something
real to test the comparison logic against. Edit STORES/ITEMS/PRICE_DATA below
to match actual stores and prices near you.
"""
from db import get_connection, init_db

STORES = ["Walmart", "Aldi", "Kroger"]

ITEMS = ["Milk", "Eggs", "Bread", "Bananas", "Chicken Breast"]

# (store_name, item_name, price)
PRICE_DATA = [
    ("Walmart", "Milk", 3.14),
    ("Walmart", "Eggs", 2.98),
    ("Walmart", "Bread", 1.98),
    ("Walmart", "Bananas", 0.58),
    ("Walmart", "Chicken Breast", 3.24),

    ("Aldi", "Milk", 3.15),
    ("Aldi", "Eggs", 2.65),
    ("Aldi", "Bread", 1.65),
    ("Aldi", "Bananas", 0.49),
    # Aldi intentionally missing "Chicken Breast" to test handling of gaps

    ("Kroger", "Milk", 3.69),
    ("Kroger", "Eggs", 3.19),
    ("Kroger", "Bread", 2.29),
    ("Kroger", "Bananas", 0.62),
    ("Kroger", "Chicken Breast", 2.99),
]


def seed():
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    store_ids = {}
    for name in STORES:
        cur.execute("INSERT OR IGNORE INTO stores (name) VALUES (?)", (name,))
        cur.execute("SELECT id FROM stores WHERE name = ?", (name,))
        store_ids[name] = cur.fetchone()["id"]

    item_ids = {}
    for name in ITEMS:
        cur.execute("INSERT OR IGNORE INTO items (name) VALUES (?)", (name,))
        cur.execute("SELECT id FROM items WHERE name = ?", (name,))
        item_ids[name] = cur.fetchone()["id"]

    for store_name, item_name, price in PRICE_DATA:
        cur.execute(
            """INSERT INTO prices (store_id, item_id, price)
               VALUES (?, ?, ?)
               ON CONFLICT(store_id, item_id) DO UPDATE SET
                   price = excluded.price,
                   last_updated = datetime('now')""",
            (store_ids[store_name], item_ids[item_name], price),
        )

    conn.commit()
    conn.close()
    print(f"Seeded {len(STORES)} stores, {len(ITEMS)} items, {len(PRICE_DATA)} prices.")


if __name__ == "__main__":
    seed()
