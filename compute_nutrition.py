"""
compute_nutrition.py
--------------------
Computes per-serving nutritional content for each meal by summing the
ingredient contributions from meal_ingredients.csv.

Nutrient data (per 100 g or 100 mL) is sourced from:
  - USDA FoodData Central (https://fdc.nal.usda.gov/)
  - Canadian Nutrient File (Health Canada)

Tracked nutrients (14):
  calories (kcal), protein (g), fat (g), carbs (g), fiber (g), sugar (g),
  sodium (mg), calcium (mg), iron (mg), potassium (mg),
  vitamin_d (IU), b12 (µg), folate (µg DFE), magnesium (mg)

Usage:
    python compute_nutrition.py
Outputs:
    data/meal_nutrients.csv
"""

import os
import pandas as pd

# ---------------------------------------------------------------------------
# Nutrient values per 100 g (or 100 mL for liquids)
# Source: USDA FoodData Central / Canadian Nutrient File
# Columns: cal, protein, fat, carbs, fiber, sugar, sodium, calcium,
#          iron, potassium, vit_d, b12, folate, magnesium
# ---------------------------------------------------------------------------
NUTRIENT_DB = {
    # ingredient_id: [cal, prot, fat, carbs, fiber, sugar, na, ca, fe, k, vitD, b12, folate, mg]
    "oats":                   [389, 17.0,  7.0, 66.0, 11.0,  1.0,   6,  54, 4.70,  429,   0,  0.00,  56, 177],
    "milk_2l":                [ 50,  3.3,  2.0,  4.8,  0.0,  5.0,  44, 125, 0.10,  150,  53,  0.45,   5,  11],
    "bananas":                [ 89,  1.1,  0.3, 23.0,  2.6, 12.0,   1,   5, 0.30,  358,   0,  0.00,  20,  27],
    "sugar":                  [387,  0.0,  0.0,100.0,  0.0,100.0,   1,   1, 0.00,    2,   0,  0.00,   0,   0],
    "eggs":                   [143, 13.0, 10.0,  1.0,  0.0,  1.0, 142,  50, 1.80,  126,  87,  0.89,  47,  12],
    "bread_white":            [265,  9.0,  3.2, 49.0,  2.7,  5.0, 491, 107, 3.60,  115,   0,  0.00,  48,  23],
    "butter":                 [717,  0.9, 81.0,  0.1,  0.0,  0.1,  11,  24, 0.00,   24,  60,  0.17,   3,   2],
    "cereal":                 [380,  7.0,  1.0, 85.0,  3.0, 25.0, 350, 100,12.00,  200, 200,  1.50, 200,  30],
    "yogurt_plain":           [ 61,  3.5,  3.3,  4.7,  0.0,  4.7,  46, 121, 0.10,  155,   0,  0.37,   7,  11],
    "flour":                  [364, 10.0,  1.0, 76.0,  2.7,  0.3,   2,  15, 1.20,  107,   0,  0.00,  28,  22],
    "peanut_butter":          [588, 25.0, 50.0, 20.0,  6.0,  9.0, 422,  49, 1.70,  558,   0,  0.00,  87, 168],
    "cheese_cheddar":         [403, 25.0, 33.0,  1.3,  0.0,  0.5, 621, 721, 0.70,   98,  24,  0.83,  18,  28],
    "pasta_spaghetti":        [371, 13.0,  1.5, 74.0,  3.2,  0.6,   6,  21, 1.30,  215,   0,  0.00,  18,  53],
    "tomato_sauce":           [ 32,  1.4,  0.4,  7.0,  1.4,  5.0, 320,  17, 1.00,  285,   0,  0.00,  10,  14],
    "olive_oil":              [884,  0.0,100.0,  0.0,  0.0,  0.0,   2,   1, 0.60,    1,   0,  0.00,   0,   0],
    "onions":                 [ 40,  1.1,  0.1,  9.3,  1.7,  4.2,   4,  23, 0.20,  146,   0,  0.00,  19,  10],
    "garlic":                 [149,  6.4,  0.5, 33.0,  2.1,  1.0,  17, 181, 1.70,  401,   0,  0.00,   3,  25],
    "white_rice":             [365,  7.0,  0.7, 80.0,  1.3,  0.0,   1,  28, 0.80,  115,   0,  0.00,   8,  25],
    "canned_black_beans":     [ 91,  5.7,  0.4, 16.0,  4.8,  0.3, 250,  48, 1.80,  260,   0,  0.00, 130,  48],
    "vegetable_oil":          [884,  0.0,100.0,  0.0,  0.0,  0.0,   0,   0, 0.00,    0,   0,  0.00,   0,   0],
    "canned_tuna":            [109, 25.0,  1.0,  0.0,  0.0,  0.0, 320,  17, 1.30,  237,   0,  3.40,   5,  29],
    "tortillas":              [306,  8.0,  7.0, 52.0,  3.0,  2.0, 500,  77, 2.80,  120,   0,  0.00,  30,  20],
    "lettuce":                [ 15,  1.4,  0.2,  2.9,  1.3,  1.8,  28,  36, 0.90,  194,   0,  0.00,  73,  14],
    "tomatoes":               [ 18,  0.9,  0.2,  3.9,  1.2,  2.6,   5,  10, 0.30,  237,   0,  0.00,  15,  11],
    "ramen_noodles":          [385, 11.0, 15.0, 55.0,  2.0,  2.0,1660,  20, 4.00,  130,   0,  0.00,  10,  25],
    "soy_sauce":              [ 53,  8.0,  0.1,  5.0,  0.8,  1.0,5493,  17, 2.50,  212,   0,  0.00,  18,  40],
    "salsa":                  [ 35,  1.5,  0.3,  7.0,  1.5,  4.0, 380,  22, 0.70,  200,   0,  0.00,  12,  12],
    "chicken_breast":         [165, 31.0,  3.6,  0.0,  0.0,  0.0,  74,  15, 1.00,  256,   5,  0.30,   4,  29],
    "frozen_mixed_veg":       [ 65,  3.0,  0.3, 13.0,  3.5,  3.0,  50,  35, 1.20,  260,   0,  0.00,  40,  20],
    "ground_beef":            [254, 26.0, 17.0,  0.0,  0.0,  0.0,  75,  18, 2.60,  318,   5,  2.50,   8,  21],
    "potatoes":               [ 77,  2.0,  0.1, 17.0,  2.2,  0.8,   6,  12, 0.80,  425,   0,  0.00,  15,  23],
    "canned_tomatoes":        [ 20,  1.0,  0.2,  4.0,  1.0,  3.0, 200,  33, 1.50,  237,   0,  0.00,  10,  14],
    "bell_peppers":           [ 31,  1.0,  0.3,  6.0,  2.1,  4.0,   4,  10, 0.40,  211,   0,  0.00,  46,  12],
    "lentils":                [352, 25.0,  1.0, 60.0, 15.0,  2.0,   6,  56, 7.50,  677,   0,  0.00, 479, 122],
    "carrots":                [ 41,  0.9,  0.2, 10.0,  2.8,  4.7,  69,  33, 0.30,  320,   0,  0.00,  19,  12],
    "frozen_chicken_nuggets": [267, 15.0, 16.0, 17.0,  1.0,  1.0, 600,  15, 1.20,  200,   0,  0.60,  10,  20],
    "salt":                   [  0,  0.0,  0.0,  0.0,  0.0,  0.0,38758, 24, 0.30,    8,   0,  0.00,   0,   1],
    "tofu":                   [ 76,  8.0,  4.5,  2.0,  0.3,  0.5,   7, 350, 2.70,  121,   0,  0.00,  15,  30],
    "spinach":                [ 23,  2.9,  0.4,  3.6,  2.2,  0.4,  79,  99, 2.70,  558,   0,  0.00, 194,  79],
    "apples":                 [ 52,  0.3,  0.2, 14.0,  2.4, 10.0,   1,   6, 0.12,  107,   0,  0.00,   3,   5],
    "broccoli":               [ 34,  2.8,  0.4,  7.0,  2.6,  1.7,  33,  47, 0.73,  316,   0,  0.00,  63,  21],
    "canned_corn":            [ 86,  3.3,  1.2, 18.0,  2.4,  5.7, 270,   4, 0.70,  254,   0,  0.00,  46,  30],
    "cream_cheese":           [342,  6.2, 34.0,  4.1,  0.0,  3.2, 321,  98, 0.40,  138,   0,  0.20,  11,   9],
    "bacon":                  [541, 37.0, 42.0,  1.4,  0.0,  0.0,1717,   5, 0.70,  565,   7,  0.80,   2,  33],
    "avocado":                [160,  2.0, 15.0,  8.5,  6.7,  0.7,   7,  12, 0.60,  485,   0,  0.00,  81,  29],
    "canned_chickpeas":       [119,  7.0,  2.0, 20.0,  5.4,  3.0, 270,  49, 1.80,  150,   0,  0.00,  60,  24],
    "honey":                  [304,  0.3,  0.0, 82.0,  0.2, 82.0,   4,   6, 0.40,   52,   0,  0.00,   2,   2],
    "shredded_mozzarella":    [300, 22.0, 22.0,  2.2,  0.0,  1.0, 627, 505, 0.40,   95,   0,  2.30,   7,  20],
    # --- New ingredients for nutrient gap coverage ---
    "canned_salmon":          [136, 20.0,  6.0,  0.0,  0.0,  0.0, 420, 249, 0.70,  326, 526,  3.26,  12,  29],
    "canned_sardines":        [208, 25.0, 11.0,  0.0,  0.0,  0.0, 505, 382, 2.90,  397, 193,  8.94,  10,  39],
    "fortified_oj":           [ 45,  0.7,  0.2, 10.0,  0.2,  8.4,   1, 140, 0.20,  200,  40,  0.00,  30,  11],
    "mixed_nuts":             [607, 20.0, 54.0, 21.0,  7.0,  4.0,   3, 100, 2.60,  632,   0,  0.00,  30, 210],
    "orange":                 [ 47,  0.9,  0.1, 12.0,  2.4,  9.4,   0,  40, 0.10,  181,   0,  0.00,  30,  10],
    "strawberries":           [ 32,  0.7,  0.3,  7.7,  2.0,  4.9,   1,  16, 0.40,  153,   0,  0.00,  24,  13],
    "frozen_berries":         [ 57,  0.7,  0.3, 14.0,  2.7,  9.0,   1,  15, 0.50,  120,   0,  0.00,  14,  13],
    "dark_chocolate":         [546,  5.0, 31.0, 60.0,  7.0, 48.0,  24,  56, 8.00,  559,   0,  0.00,  12, 146],
    "kale":                   [ 49,  4.3,  0.9,  9.0,  3.6,  2.3,  38, 150, 1.50,  491,   0,  0.00,  62,  47],
    "canned_kidney_beans":    [ 84,  5.5,  0.5, 15.0,  5.3,  1.8, 256,  28, 1.50,  260,   0,  0.00, 100,  37],
}

NUTRIENT_COLS = [
    "calories", "protein_g", "fat_g", "carbs_g", "fiber_g", "sugar_g",
    "sodium_mg", "calcium_mg", "iron_mg", "potassium_mg",
    "vitamin_d_iu", "b12_mcg", "folate_mcg_dfe", "magnesium_mg",
]


def compute_meal_nutrients(
    meals_path="data/meals.csv",
    ingredients_path="data/meal_ingredients.csv",
    output_path="data/meal_nutrients.csv",
):
    meals = pd.read_csv(meals_path)
    ing = pd.read_csv(ingredients_path)

    records = []
    for _, meal in meals.iterrows():
        mid = meal["meal_id"]
        meal_ings = ing[ing["meal_id"] == mid]

        totals = [0.0] * len(NUTRIENT_COLS)
        for _, row in meal_ings.iterrows():
            iid = row["ingredient_id"]
            amount = row["amount_needed"]   # in g or mL
            if iid not in NUTRIENT_DB:
                print(f"  WARNING: no nutrient data for '{iid}' (meal {mid})")
                continue
            # All NUTRIENT_DB values are per 100 g/mL
            factor = amount / 100.0
            nvals = NUTRIENT_DB[iid]
            for idx, val in enumerate(nvals):
                totals[idx] += val * factor

        record = {"meal_id": mid}
        for col, val in zip(NUTRIENT_COLS, totals):
            record[col] = round(val, 2)
        records.append(record)

    df = pd.DataFrame(records)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"Saved {len(df)} meal nutrition rows -> {output_path}")
    return df


if __name__ == "__main__":
    df = compute_meal_nutrients()
    print(df.to_string(index=False))
