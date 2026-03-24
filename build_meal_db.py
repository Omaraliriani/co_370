"""
build_meal_db.py
----------------
Validates the meal database for consistency:
  - All meal_ids in meal_ingredients.csv exist in meals.csv
  - All ingredient_ids in meal_ingredients.csv exist in ingredient_prices.csv
  - Every meal has at least one ingredient
  - Units match the package_unit for each ingredient
  - Prints a summary report

Usage:
    python build_meal_db.py
"""

import pandas as pd
import sys


def validate():
    meals = pd.read_csv("data/meals.csv")
    ingredients_csv = pd.read_csv("data/meal_ingredients.csv")
    prices = pd.read_csv("data/ingredient_prices.csv")

    errors = []
    warnings = []

    known_meal_ids = set(meals["meal_id"])
    known_ingredient_ids = set(prices["ingredient_id"])

    # Check meal_ids
    for mid in ingredients_csv["meal_id"].unique():
        if mid not in known_meal_ids:
            errors.append(f"Unknown meal_id '{mid}' in meal_ingredients.csv")

    # Check ingredient_ids and unit consistency
    price_units = prices.set_index("ingredient_id")["package_unit"].to_dict()
    for _, row in ingredients_csv.iterrows():
        iid = row["ingredient_id"]
        if iid not in known_ingredient_ids:
            errors.append(
                f"Unknown ingredient_id '{iid}' in meal {row['meal_id']}"
            )
        else:
            expected_unit = price_units[iid]
            if row["unit"] != expected_unit:
                errors.append(
                    f"Unit mismatch for '{iid}' in meal {row['meal_id']}: "
                    f"got '{row['unit']}', expected '{expected_unit}'"
                )

    # Every meal must appear in meal_ingredients
    meal_ids_with_ingredients = set(ingredients_csv["meal_id"])
    for mid in known_meal_ids:
        if mid not in meal_ids_with_ingredients:
            errors.append(f"Meal '{mid}' has no ingredients in meal_ingredients.csv")

    # Check meal type distribution
    type_counts = meals["meal_type"].value_counts()
    for t, minimum in [("B", 6), ("L", 7), ("D", 7)]:
        count = type_counts.get(t, 0)
        if count < minimum:
            warnings.append(
                f"Only {count} {t} meals (minimum {minimum} recommended)"
            )

    # Summary
    print("=" * 60)
    print("Meal Database Validation Report")
    print("=" * 60)
    print(f"Meals          : {len(meals)} total")
    for t in ["B", "L", "D"]:
        label = {"B": "Breakfast", "L": "Lunch", "D": "Dinner"}[t]
        print(f"  {label:<12}: {type_counts.get(t, 0)}")
    print(f"Ingredients    : {len(prices)} items in price list")
    print(f"Recipe rows    : {len(ingredients_csv)}")
    print()

    if errors:
        print(f"ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  ✗ {e}")
    else:
        print("No errors found.")

    if warnings:
        print(f"\nWARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  WARNING: {w}")

    print()
    # Per-meal ingredient count
    print("Ingredients per meal:")
    counts = ingredients_csv.groupby("meal_id").size().reset_index(name="n_ingredients")
    merged = meals.merge(counts, on="meal_id")
    for _, row in merged.iterrows():
        print(f"  {row['meal_id']:4s}  {row['meal_name']:<35s}  {row['n_ingredients']} ingredients")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    validate()
