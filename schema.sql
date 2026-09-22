-- Stores: the physical/chain locations we're tracking
CREATE TABLE IF NOT EXISTS stores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    latitude REAL,
    longitude REAL
);

-- Items: the master list of things we track prices for
-- (name is unique so "Milk (Gallon)" always refers to the same item across stores)
-- unit_type is one of: 'oz' (weight), 'fl_oz' (volume), 'count' (discrete items)
-- — this is fixed per item, so every store's price for it is entered in
-- that unit, even if the actual package size differs store to store.
--
-- family groups size variants of "the same" grocery item together (e.g.
-- "Milk (Half Gallon)" and "Milk (Gallon)" might both have family="Milk"),
-- so searching "milk" finds both. is_default marks which ONE variant per
-- family gets picked automatically when someone just types the family
-- name and hits enter, instead of asking them to choose a size.
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    unit_type TEXT,
    family TEXT,
    is_default INTEGER NOT NULL DEFAULT 1
);

-- Prices: what a given item costs at a given store, and when we last checked
-- quantity is how much you actually get for that price, in the item's
-- unit_type (e.g. 128 for a gallon of milk tracked in fl_oz). This is what
-- makes different package sizes across stores comparable by unit price.
CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    price REAL NOT NULL,
    quantity REAL NOT NULL DEFAULT 1,
    last_updated TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (store_id) REFERENCES stores(id),
    FOREIGN KEY (item_id) REFERENCES items(id),
    UNIQUE(store_id, item_id)  -- one price per item per store (update it, don't duplicate)
);
