"""
Interactive list builder (v1).

Lets you type item names one at a time, matches them against what's
actually in the database (so typos/partial names still work), and then
runs the existing comparison report on whatever list you build.

Run this instead of compare.py directly once you want to type a list
instead of editing the hardcoded sample_list.
"""
import difflib

from db import get_connection
from compare import print_report

# How similar a typed word needs to be to an item name (0.0-1.0) before
# we'll suggest it as a "did you mean" guess. Lower = more forgiving of
# typos, but more likely to suggest something you didn't mean.
FUZZY_MATCH_THRESHOLD = 0.6


def get_all_item_names():
    """Returns every item name currently in the database, for matching against."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM items ORDER BY name")
    names = [row["name"] for row in cur.fetchall()]
    conn.close()
    return names


def find_matching_item(user_input, all_items):
    """
    Tries to match what the user typed to a real item name, in three stages:
      1. Exact match (case-insensitive) — "milk" -> "Milk"
      2. Substring match — "chick" -> "Chicken Breast"
      3. Fuzzy/typo match — "mikl" -> asks "did you mean 'Milk'?"

    Returns the matched item name, or None if nothing reasonable matched
    (or the user declined a fuzzy suggestion).
    """
    user_input = user_input.strip().lower()

    # Stage 1: exact match (case-insensitive)
    for item in all_items:
        if item.lower() == user_input:
            return item

    # Stage 2: typed text is contained in the item name
    partial_matches = [item for item in all_items if user_input in item.lower()]
    if len(partial_matches) == 1:
        return partial_matches[0]
    elif len(partial_matches) > 1:
        print(f"  '{user_input}' matches multiple items: {', '.join(partial_matches)}")
        print("  Please be more specific.")
        return None

    # Stage 3: fuzzy match for actual misspellings (e.g. "mikl" -> "Milk").
    # get_close_matches scores similarity and returns the best guesses.
    close_matches = difflib.get_close_matches(
        user_input,
        [item.lower() for item in all_items],
        n=1,
        cutoff=FUZZY_MATCH_THRESHOLD,
    )

    if close_matches:
        # Map the lowercase match back to its real, properly-cased name
        guess = next(item for item in all_items if item.lower() == close_matches[0])
        confirm = input(f"  Did you mean '{guess}'? (y/n): ").strip().lower()
        if confirm in ("y", "yes"):
            return guess

    return None


def build_list_interactively():
    """
    Prompts the user to type items one at a time until they're done.
    Returns the final list of matched item names.
    """
    all_items = get_all_item_names()

    if not all_items:
        print("No items found in the database. Run seed.py first.")
        return []

    print("Available items:", ", ".join(all_items))
    print("Type an item name to add it to your list.")
    print("Type 'done' when finished, or 'list' to see what's in the database again.\n")

    grocery_list = []

    while True:
        user_input = input("> ").strip()

        if not user_input:
            continue

        if user_input.lower() == "done":
            break

        if user_input.lower() == "list":
            print("Available items:", ", ".join(all_items))
            continue

        matched = find_matching_item(user_input, all_items)

        if matched:
            if matched in grocery_list:
                print(f"  '{matched}' is already on your list.")
            else:
                grocery_list.append(matched)
                print(f"  Added: {matched}")
        else:
            print(f"  No item found matching '{user_input}'. "
                  f"Type 'list' to see available items.")

    return grocery_list


if __name__ == "__main__":
    my_list = build_list_interactively()

    if my_list:
        print_report(my_list)
    else:
        print("\nNo items added — nothing to compare.")
