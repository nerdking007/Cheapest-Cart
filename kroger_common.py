"""
Shared Kroger API logic used by both kroger_sync.py and kroger_discover.py.

THE "BRIDGE" BETWEEN NAMING SCHEMES:
Kroger's product names are specific and brand-heavy (e.g. "Kroger 2%
Reduced Fat Milk"), while your prices.csv uses simple generic names
("Milk, Whole (Gallon)"). Text alone can't reliably bridge that gap every
time, so once a match is confirmed by a human, it's saved permanently in
kroger_mapping.csv as (your item name -> Kroger's exact product ID).
Every future sync looks up that exact ID directly — fast, no re-matching,
no repeated guessing — and only falls back to a fresh search if an item
has no saved mapping yet, or its saved product ID stops returning data
(e.g. discontinued).
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
MAPPING_PATH = os.path.join(os.path.dirname(__file__), "kroger_mapping.csv")
KROGER_COLUMN_NAME = "Kroger"
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


def get_credentials_or_exit():
    client_id = os.environ.get("KROGER_CLIENT_ID")
    client_secret = os.environ.get("KROGER_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Set KROGER_CLIENT_ID and KROGER_CLIENT_SECRET as environment "
              "variables first.")
        sys.exit(1)
    return client_id, client_secret


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

    return selected["locationId"], lat, lon


def search_by_term(token, location_id, search_term, limit=10, start=None):
    """Searches Kroger's product catalog for a term at a specific store."""
    params = {"filter.term": search_term, "filter.locationId": location_id, "filter.limit": limit}
    if start is not None:
        params["filter.start"] = start
    response = requests.get(
        PRODUCTS_URL,
        headers={"Authorization": f"Bearer {token}"},
        params=params,
    )
    response.raise_for_status()
    return response.json().get("data", [])


def get_by_product_id(token, location_id, product_id):
    """
    Fetches ONE exact product by its Kroger productId — this is the fast path
    for items that already have a saved mapping, since it needs no fuzzy term
    search or human re-confirmation, just a direct lookup.
    Returns the product dict, or None if it's no longer available.
    """
    response = requests.get(
        PRODUCTS_URL,
        headers={"Authorization": f"Bearer {token}"},
        params={"filter.productId": product_id, "filter.locationId": location_id},
    )
    response.raise_for_status()
    results = response.json().get("data", [])
    return results[0] if results else None


def parse_size_to_quantity(size_text, unit_type):
    """
    Best-effort parse of Kroger's free-text size field (e.g. "1 gal",
    "12 ct", "5 lb") into a number matching the item's unit_type
    (oz, fl_oz, or count). Returns None if it can't confidently parse —
    the caller should then ask for the quantity manually instead of
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

    return None


def load_mapping():
    """Returns {item_name: kroger_product_id} from kroger_mapping.csv (empty dict if none yet)."""
    if not os.path.exists(MAPPING_PATH):
        return {}
    with open(MAPPING_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        return {row[0]: row[1] for row in reader if len(row) >= 2 and row[0]}


def save_mapping(mapping):
    """Writes the full {item_name: kroger_product_id} dict back to kroger_mapping.csv."""
    with open(MAPPING_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Item", "KrogerProductId"])
        for item_name, product_id in mapping.items():
            writer.writerow([item_name, product_id])
