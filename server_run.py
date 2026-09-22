"""
One-command startup: run this instead of remembering the right order
of seed/import/location scripts every time.

    python3 server_run.py

What it does, in order:
  1. Reloads prices.csv into the database (picks up any spreadsheet edits)
  2. Re-sets store coordinates (safe to rerun — just updates lat/long)
  3. Starts the web app at http://127.0.0.1:5000

Press Ctrl+C in the terminal to stop the server when you're done.
"""
from import_prices import import_prices
from set_store_locations import set_store_locations

print("Step 1/3: Importing prices.csv into the database...")
import_prices()

print("\nStep 2/3: Setting store coordinates...")
set_store_locations()

print("\nStep 3/3: Starting the web app...")
print("Open http://127.0.0.1:5000 in your browser. Press Ctrl+C to stop.\n")
"""    #same comp only
from app import app
app.run(debug=True, use_reloader=False)
"""
#local network
from app import app
app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)