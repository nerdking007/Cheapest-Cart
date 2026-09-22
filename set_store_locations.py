"""
Sets latitude/longitude for the 5 real stores, so distance can be
calculated between the shopper's location and each store.

IMPORTANT: these coordinates are close estimates based on each store's
street address, not pulled from an exact geocoding service. They should
be accurate to within a couple hundred feet, which is plenty for
straight-line distance decisions, but if you want pinpoint accuracy:
  1. Open Google Maps
  2. Search the store's address
  3. Right-click the exact pin -> click the lat/lng numbers to copy them
  4. Replace the values below

Run this once (or whenever you add/adjust a store):
    python3 set_store_locations.py
"""
from db import get_connection, init_db

# (store_name, latitude, longitude)
STORE_LOCATIONS = [
    ("Walmart",       37.9436, -91.7768),  # 500 S Bishop Ave, Rolla
    ("Aldi",          37.9580, -91.7793),  # 500 W State Route 72, Rolla
    ("Kroger",        37.9531, -91.7771),  # 605 W 4th St, Rolla
    ("Price Chopper", 37.9464, -91.8012),  # 1360 Forum Dr, Rolla
    ("Rays Discount Grocery", 37.9331, -91.7549),  # 1405 Highway OO, Rolla
]


def set_store_locations():
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    for name, lat, lon in STORE_LOCATIONS:
        cur.execute(
            "UPDATE stores SET latitude = ?, longitude = ? WHERE name = ?",
            (lat, lon, name),
        )
        if cur.rowcount == 0:
            # Store doesn't exist in the database yet — create it with location set
            cur.execute(
                "INSERT INTO stores (name, latitude, longitude) VALUES (?, ?, ?)",
                (name, lat, lon),
            )

    conn.commit()
    conn.close()
    print(f"Set coordinates for {len(STORE_LOCATIONS)} stores.")


if __name__ == "__main__":
    set_store_locations()
