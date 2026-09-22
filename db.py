"""
Handles connecting to the local SQLite database and setting up the schema.
Run this file directly to (re)create grocery.db from schema.sql.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "grocery.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def get_connection():
    """Returns a connection to the local grocery database."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row  # lets us access columns by name
    return conn


def init_db():
    """Creates the database tables if they don't already exist, and
    migrates older databases that predate the unit_type/quantity columns."""
    conn = get_connection()
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())

    # Safe to run every time — SQLite errors if the column already exists,
    # which we just ignore, so this works whether the db is brand new or old.
    try:
        conn.execute("ALTER TABLE items ADD COLUMN unit_type TEXT")
    except sqlite3.OperationalError:
        pass  # already has the column

    try:
        conn.execute("ALTER TABLE prices ADD COLUMN quantity REAL NOT NULL DEFAULT 1")
    except sqlite3.OperationalError:
        pass  # already has the column

    try:
        conn.execute("ALTER TABLE items ADD COLUMN family TEXT")
    except sqlite3.OperationalError:
        pass  # already has the column

    try:
        conn.execute("ALTER TABLE items ADD COLUMN is_default INTEGER NOT NULL DEFAULT 1")
    except sqlite3.OperationalError:
        pass  # already has the column

    conn.commit()
    conn.close()
    print(f"Database ready at {DB_PATH}")


if __name__ == "__main__":
    init_db()
