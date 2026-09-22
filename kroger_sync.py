"""
Pulls current prices from Kroger's public API for your tracked items and
writes them into prices.csv's Kroger column — an alternative to manually
checking Kroger's prices in-store or on their site.

WHY A SEPARATE SYNC SCRIPT (not live inside the app itself):
Calling Kroger's API on every page load would slow the app down, add
network-failure handling everywhere, and risk hitting Kroger's rate
limits. Run this occasionally instead (e.g. once a week) to refresh
prices.csv, then run server_run.py as usual — the app itself stays fast
and doesn't depend on Kroger's servers being up to work.

SETUP (one-time):
  1. Register at https://developer.kroger.com — create an account, then
     register an application to get a CLIENT_ID and CLIENT_SECRET.
  2. Set them as environment variables (NOT hardcoded here) so they never
     end up saved in a file that could get shared, e.g. via Google Drive:
       macOS/Linux:            export KROGER_CLIENT_ID=your_id
                                export KROGER_CLIENT_SECRET=your_secret
       Windows (PowerShell):   $env:KROGER_CLIENT_ID="your_id"
                               $env:KROGER_CLIENT_SECRET="your_secret"
     (You'll need to set these each new terminal session, unless you add
     them to your shell profile / a permanent Windows environment variable.)
  3. pip install requests

USAGE:
    python3 kroger_sync.py

This asks you to confirm your store location once (by zip code), then
walks through each item in prices.csv, showing what it found on Kroger's
site so YOU confirm the match before anything gets written — nothing is
guessed silently.

HONEST LIMITATIONS:
- Kroger's product search can return multiple/irrelevant results for
  vague terms — that's exactly why this asks you to pick, rather than
  auto-selecting the first result.
- Package size comes back as free text (e.g. "1 gal", "12 ct") which this
  tries to convert automatically into your item's unit — when it can't
  confidently parse it, it'll ask you to type the quantity by hand instead
  of guessing wrong.
"""
import base64
import csv
import os
import re
import sys

import requests

TOKEN_URL = "https://api.kroger.com/v1/connect/oauth2/token"
LOCATIONS_URL = "https://api.kroger.com/v1/locations"
PRODUCTS_URL = "https://api.kroger.com/v1/products"

CSV_PATH = os.path.join(os.path.dirname(__file__), "prices.csv")
KROGER_COLUMN_NAME = "Kroger"  # must match the header exactly in prices.csv
ZIP_CODE = "65401"  # Rolla, MO — change if you're syncing a different store


def get_access_token(client_id, client_secret):
    """OAuth2 client_credentials flow — gets a token for public product/location data."""
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    response = requests.post(
        TOKEN_URL,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {credentials}",
        },
        data={"grant_type": "client_credentials", "scope": "product.compact"},
    )
    response.raise_for_status()
    return response.json()["access_token"]


def find_store_location(token, zip_code):
    """Looks up nearby Kroger stores by zip code and lets you confirm which one is yours.
    Returns (location_id, latitude, longitude) — the lat/long come straight from
    Kroger's own records, so they're more accurate than a manually estimated value.
    """
    response = requests.get(
        LOCATIONS_URL,
        headers={"Authorization": f"Bearer {token}"},
        params={"filter.zipCode.near": zip_code, "filter.limit": 5},
    )
    response.raise_for_status()
    stores = response.json().get("data", [])

    if not stores:
        print(f"No Kroger stores found near zip code {zip_code}.")
        sys.exit(1)

    print("\nNearby Kroger stores:")
    for i, store in enumerate(stores):
        address = store.get("address", {})
        print(f"  {i + 1}. {store.get('name', 'Unknown')} — "
              f"{address.get('addressLine1', '')}, {address.get('city', '')}")

    choice = input(f"\nWhich one is yours? (1-{len(stores)}): ").strip()
    try:
        selected = stores[int(choice) - 1]
    except (ValueError, IndexError):
        print("Invalid choice.")
        sys.exit(1)

    geo = selected.get("geolocation", {})
    lat, lon = geo.get("latitude"), geo.get("longitude")
    if lat is not None and lon is not None:
        print(f"  Real coordinates from Kroger: {lat}, {lon}")
        print(f"  (Consider updating set_store_locations.py's Kroger entry to "
              f"this exact value instead of an estimate.)")

    return selected["locationId"], lat, lon


def search_product(token, location_id, search_term):
    """Searches Kroger's product catalog for a term at a specific store."""
    response = requests.get(
        PRODUCTS_URL,
        headers={"Authorization": f"Bearer {token}"},
        params={"filter.term": search_term, "filter.locationId": location_id, "filter.limit": 5},
    )
    response.raise_for_status()
    return response.json().get("data", [])


def parse_size_to_quantity(size_text, unit_type):
    """
    Best-effort parse of Kroger's free-text size field (e.g. "1 gal",
    "12 ct", "5 lb") into a number matching the item's unit_type
    (oz, fl_oz, or count). Returns None if it can't confidently parse —
    the caller then asks you to type the quantity manually instead of
    silently guessing wrong.
    """
    if not size_text:
        return None
    text = size_text.lower().strip()
    match = re.search(r"([\d.]+)\s*([a-z]+)", text)
    if not match:
        return None
    amount, unit_word = float(match.group(1)), match.group(2)

    if unit_type == "fl_oz":
        if "gal" in unit_word:
            return amount * 128
        if "qt" in unit_word:
            return amount * 32
        if "fl" in unit_word or "oz" in unit_word:
            return amount
    elif unit_type == "oz":
        if "lb" in unit_word or "pound" in unit_word:
            return amount * 16
        if "oz" in unit_word:
            return amount
    elif unit_type == "count":
        if "ct" in unit_word or "count" in unit_word or "ea" in unit_word:
            return amount

    return None  # couldn't confidently match the unit


def sync():
    client_id = os.environ.get("KROGER_CLIENT_ID")
    client_secret = os.environ.get("KROGER_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("Set KROGER_CLIENT_ID and KROGER_CLIENT_SECRET as environment "
              "variables first (see the top of this file for instructions).")
        sys.exit(1)

    print("Getting access token...")
    token = get_access_token(client_id, client_secret)

    location_id, store_lat, store_lon = find_store_location(token, ZIP_CODE)
    print(f"Using Kroger location: {location_id}")

    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    header = rows[0]
    if KROGER_COLUMN_NAME not in header:
        print(f"Couldn't find a '{KROGER_COLUMN_NAME}' column in {CSV_PATH}.")
        sys.exit(1)
    kroger_col = header.index(KROGER_COLUMN_NAME)

    updated = 0
    try:
        for row in rows[1:]:
            if not row or not row[0].strip():
                continue

            item_name = row[0].strip()
            family = row[1].strip() if len(row) > 1 and row[1].strip() else item_name
            unit_type = row[3].strip().lower() if len(row) > 3 else "oz"

            if len(family) < 3:
                print(f"\nSkipping '{item_name}': search term '{family}' is too short "
                      f"(Kroger requires at least 3 characters).")
                continue

            print(f"\nSearching Kroger for: {family} ({item_name})")
            candidates = search_product(token, location_id, family)

            if not candidates:
                print("  No matches found — skipping.")
                continue

            for i, product in enumerate(candidates):
                desc = product.get("description", "Unknown")
                items = product.get("items", [])
                price_info = items[0].get("price", {}) if items else {}
                size = items[0].get("size", "") if items else ""
                sold_by = items[0].get("soldBy", "") if items else ""
                price = price_info.get("regular")
                print(f"  {i + 1}. {desc} — {size} — "
                      f"{'$' + str(price) if price else 'no price available'}")
                # soldBy is Kroger's own record of how the item is actually sold —
                # a mismatch against your spreadsheet's unit_type is worth a heads
                # up (e.g. you tracked it as count but Kroger sells it by weight).
                expected_sold_by = "weight" if unit_type == "oz" else "unit"
                if sold_by and sold_by != expected_sold_by:
                    print(f"     note: Kroger lists this as sold by '{sold_by}', but "
                          f"your sheet tracks '{item_name}' as '{unit_type}' — "
                          f"double check this is the right match.")

            choice = input("  Which matches this item? (number, or 's' to skip): ").strip().lower()
            if choice == "s" or not choice:
                continue

            try:
                product = candidates[int(choice) - 1]
            except (ValueError, IndexError):
                print("  Invalid choice, skipping.")
                continue

            items = product.get("items", [])
            if not items or items[0].get("price", {}).get("regular") is None:
                print("  No price available for that item, skipping.")
                continue

            price = items[0]["price"]["regular"]
            size_text = items[0].get("size", "")
            quantity = parse_size_to_quantity(size_text, unit_type)

            if quantity is None:
                manual = input(f"  Couldn't parse size '{size_text}' as {unit_type} — "
                                f"enter quantity manually (or blank to skip): ").strip()
                if not manual:
                    continue
                try:
                    quantity = float(manual)
                except ValueError:
                    print("  Invalid number, skipping.")
                    continue

            row[kroger_col] = f"{price}@{quantity:g}"
            print(f"  Set: {price}@{quantity:g}")
            updated += 1

            # Save after every confirmed item — a network error or rate limit
            # partway through won't lose the matches you've already confirmed.
            with open(CSV_PATH, "w", newline="") as f:
                csv.writer(f).writerows(rows)
    finally:
        # Also save on the way out even if something above raised partway
        # through (e.g. a network error) — whatever was confirmed sticks.
        with open(CSV_PATH, "w", newline="") as f:
            csv.writer(f).writerows(rows)

    print(f"\nUpdated {updated} Kroger prices in {os.path.basename(CSV_PATH)}.")
    print("Run 'python3 import_prices.py' (or server_run.py) to load these into the app.")


if __name__ == "__main__":
    sync()
