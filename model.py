"""
model.py
--------
Mixed-Integer Programming meal planning optimizer for CO 370.

Minimizes total grocery cost + cost-weighted waste penalty over a 7-day plan
(7 x 3 = 21 meals) subject to nutritional, variety, and supply constraints.

Usage:
    python model.py [--lam 0.5] [--relax]

Options:
    --lam   Waste penalty parameter lambda (default: 0.5)
    --relax Use food-achievable nutrient bounds (relaxes Vit D, Mg, K lower
            bounds to levels reachable from this meal database)
"""

import argparse
import os
import sys

import pandas as pd
import gurobipy as gp
from gurobipy import GRB

# ---------------------------------------------------------------------------
# Nutrient bounds — from Health Canada DRIs for adults 19-30
# (nutrient_name: (LB, UB))
# ---------------------------------------------------------------------------
NUT_BOUNDS_STRICT = {
    "calories":       (1800,   2500),
    "protein_g":      (  46,    175),
    "fat_g":          (  44,     78),
    "carbs_g":        ( 225,    325),
    "fiber_g":        (  25,     60),
    "sugar_g":        (   0,     50),
    "sodium_mg":      ( 500,   2300),
    "calcium_mg":     (1000,   2500),
    "iron_mg":        (   8,     45),
    "potassium_mg":   (2600,   4700),
    "vitamin_d_iu":   ( 600,   4000),
    "b12_mcg":        ( 2.4,    200),
    "folate_mcg_dfe": ( 400,   1000),
    "magnesium_mg":   ( 310,    420),
}

# Relaxed bounds: used when --relax is passed.
#
# Analysis of joint infeasibility in this meal database:
#   1. Vitamin D: max achievable ~378 IU/day (B3+L6+D5); food alone cannot
#      reach the 600 IU DRI — supplementation is needed.
#   2. Calcium + Calories conflict: the calcium-rich meals (grilled cheese,
#      quesadilla, baked potato) are low-calorie, while the high-calorie
#      dinners (stir-fry, bolognese, fried rice) are low-calcium. No single
#      day can simultaneously achieve Ca >= 1000 mg AND cal >= 1800 kcal.
#   3. Fiber + Calcium conflict: high-fiber meals (beans, lentils, oats) are
#      low-calcium; high-calcium meals (dairy) are low-fiber. Max achievable
#      simultaneously is ~Ca 988 + fiber 37 (B1+L1+D7), still under Ca=1000.
#   4. B5 (Yogurt+Banana, 229 kcal) is excluded by the 1800 kcal/day LB
#      since max(B5 + any L + any D) = 1772 kcal < 1800.
#   5. Magnesium LB 310 mg requires B1 or a high-Mg dinner on every day,
#      which is infeasible given the 3-use variety limit on B1.
#
# The relaxed bounds represent ~50-70% of DRI targets — a realistic
# goal for a student food-only diet without supplementation.
# These are used for Phases 2 and 3. The strict bounds are kept in the
# model definition to demonstrate constraint tightness in the report.
NUT_BOUNDS_RELAXED = {
    "calories":       (1800, 2800),   # unchanged; any sensible plan needs this
    "protein_g":      ( 35,   200),   # ~75% of DRI
    "fat_g":          ( 15,   120),   # lower LB; some low-fat combos exist
    "carbs_g":        (120,   450),   # ~53% of DRI LB
    "fiber_g":        ( 10,    80),   # ~40% of DRI; hard to hit 25g every day
    "sugar_g":        (  0,    80),   # slightly higher UB for student diet
    "sodium_mg":      (300,  3500),   # higher UB; ramen+nuggets exceed 2300
    "calcium_mg":     (400,  2500),   # ~40% of DRI; Ca+cal conflict above
    "iron_mg":        (  4,    45),   # ~50% of DRI
    "potassium_mg":   (900,  4700),   # ~35% of DRI; B2/B4 are low-K
    "vitamin_d_iu":   ( 30,  4000),   # ~5% of DRI; food-only limitation
    "b12_mcg":        (0.5,   200),   # ~21% of DRI
    "folate_mcg_dfe": ( 80,  1200),   # ~20% of DRI
    "magnesium_mg":   ( 50,   500),   # ~16% of DRI; very hard from this DB
}

NUTRIENTS = list(NUT_BOUNDS_STRICT.keys())

DAYS = list(range(1, 8))    # 1 .. 7


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data():
    prices    = pd.read_csv("data/ingredient_prices.csv")
    meals     = pd.read_csv("data/meals.csv")
    meal_ings = pd.read_csv("data/meal_ingredients.csv")
    meal_nuts = pd.read_csv("data/meal_nutrients.csv")
    return prices, meals, meal_ings, meal_nuts


def build_params(prices, meals, meal_ings, meal_nuts):
    """Return dicts/sets used directly in the model."""
    # Sets
    ingredients = prices["ingredient_id"].tolist()
    meal_ids    = meals["meal_id"].tolist()
    B = meals[meals["meal_type"] == "B"]["meal_id"].tolist()
    L = meals[meals["meal_type"] == "L"]["meal_id"].tolist()
    D = meals[meals["meal_type"] == "D"]["meal_id"].tolist()

    # p[j] = price per package ($)
    p = prices.set_index("ingredient_id")["price_cad"].to_dict()
    # s[j] = package size (g or mL)
    s = prices.set_index("ingredient_id")["package_size"].to_dict()

    # r[(m, j)] = amount of ingredient j in meal m (g or mL)
    r = {}
    for _, row in meal_ings.iterrows():
        r[(row["meal_id"], row["ingredient_id"])] = float(row["amount_needed"])

    # a[(m, n)] = amount of nutrient n in meal m
    a = {}
    for _, row in meal_nuts.iterrows():
        for n in NUTRIENTS:
            a[(row["meal_id"], n)] = float(row[n])

    return ingredients, meal_ids, B, L, D, p, s, r, a


# ---------------------------------------------------------------------------
# Model construction
# ---------------------------------------------------------------------------

def build_model(ingredients, meal_ids, B, L, D, p, s, r, a,
                lam=0.5, nut_bounds=None):

    if nut_bounds is None:
        nut_bounds = NUT_BOUNDS_STRICT

    m = gp.Model("MealPlanner")
    m.setParam("OutputFlag", 1)

    # ------------------------------------------------------------------
    # Decision variables
    # ------------------------------------------------------------------
    # x[meal, day] in {0,1}
    x = m.addVars(meal_ids, DAYS, vtype=GRB.BINARY, name="x")
    # y[j] in Z+ — number of packages of ingredient j to buy
    y = m.addVars(ingredients, vtype=GRB.INTEGER, lb=0, name="y")
    # w[j] >= 0 — waste of ingredient j (in g or mL)
    w = m.addVars(ingredients, vtype=GRB.CONTINUOUS, lb=0, name="w")

    # ------------------------------------------------------------------
    # Objective: min total grocery cost + lambda * cost-weighted waste
    # ------------------------------------------------------------------
    grocery_cost = gp.quicksum(p[j] * y[j] for j in ingredients)
    waste_cost   = gp.quicksum((p[j] / s[j]) * w[j] for j in ingredients)
    m.setObjective(grocery_cost + lam * waste_cost, GRB.MINIMIZE)

    # ------------------------------------------------------------------
    # C1-C3: Exactly one breakfast / lunch / dinner per day
    # ------------------------------------------------------------------
    for i in DAYS:
        m.addConstr(gp.quicksum(x[b, i] for b in B) == 1, name=f"C1_d{i}")
        m.addConstr(gp.quicksum(x[l, i] for l in L) == 1, name=f"C2_d{i}")
        m.addConstr(gp.quicksum(x[d, i] for d in D) == 1, name=f"C3_d{i}")

    # ------------------------------------------------------------------
    # C4-C6: Repetition limits
    # ------------------------------------------------------------------
    for b in B:
        m.addConstr(gp.quicksum(x[b, i] for i in DAYS) <= 3, name=f"C4_{b}")
    for l in L:
        m.addConstr(gp.quicksum(x[l, i] for i in DAYS) <= 2, name=f"C5_{l}")
    for d in D:
        m.addConstr(gp.quicksum(x[d, i] for i in DAYS) <= 2, name=f"C6_{d}")

    # ------------------------------------------------------------------
    # C7: No consecutive repetition
    # ------------------------------------------------------------------
    for meal in meal_ids:
        for i in range(1, 7):
            m.addConstr(x[meal, i] + x[meal, i + 1] <= 1,
                        name=f"C7_{meal}_d{i}")

    # ------------------------------------------------------------------
    # C8: Daily nutrient requirements
    # ------------------------------------------------------------------
    for i in DAYS:
        for n in NUTRIENTS:
            lb, ub = nut_bounds[n]
            daily = gp.quicksum(a[(meal, n)] * x[meal, i] for meal in meal_ids)
            m.addConstr(daily >= lb, name=f"C8_lb_{n}_d{i}")
            m.addConstr(daily <= ub, name=f"C8_ub_{n}_d{i}")

    # ------------------------------------------------------------------
    # C9: Weekly calorie bounds
    # ------------------------------------------------------------------
    weekly_cal = gp.quicksum(
        a[(meal, "calories")] * x[meal, i]
        for meal in meal_ids for i in DAYS
    )
    m.addConstr(weekly_cal >= 7 * 1800, name="C9_lb")
    m.addConstr(weekly_cal <= 7 * 2500, name="C9_ub")

    # ------------------------------------------------------------------
    # C10-C11: Ingredient supply and waste balance
    #   w[j] = y[j]*s[j] - sum_{m,i} r[m,j]*x[m,i]    (w[j] >= 0 => supply)
    # ------------------------------------------------------------------
    for j in ingredients:
        total_usage = gp.quicksum(
            r[(meal, j)] * x[meal, i]
            for meal in meal_ids for i in DAYS
            if (meal, j) in r
        )
        m.addConstr(w[j] == y[j] * s[j] - total_usage, name=f"C11_{j}")

    return m, x, y, w


# ---------------------------------------------------------------------------
# Results reporting
# ---------------------------------------------------------------------------

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MEAL_TYPE_LABEL = {"B": "Breakfast", "L": "Lunch", "D": "Dinner"}


def print_and_save_results(m, x, y, w, ingredients, meal_ids, B, L, D,
                            p, s, r, a, meals_df, prices_df, lam):

    os.makedirs("results", exist_ok=True)

    obj = m.ObjVal
    print("\n" + "=" * 65)
    print(f"  OPTIMAL OBJECTIVE VALUE : ${obj:.4f}")
    print("=" * 65)

    # ---- Compute cost breakdown ----
    grocery_total = sum(p[j] * round(y[j].X) for j in ingredients)
    waste_total   = sum((p[j] / s[j]) * w[j].X for j in ingredients)
    print(f"  Total grocery cost       : ${grocery_total:.2f}")
    print(f"  Waste penalty (lambda={lam}): ${lam * waste_total:.2f}  "
          f"(raw waste cost ${waste_total:.2f})")

    # ---- 7-day meal plan ----
    meal_name_map = meals_df.set_index("meal_id")["meal_name"].to_dict()
    meal_type_map = meals_df.set_index("meal_id")["meal_type"].to_dict()

    plan_rows = []
    print("\n--- 7-Day Meal Plan ---")
    for i in DAYS:
        print(f"\n  {DAY_NAMES[i-1]} (Day {i})")
        for meal_set, label in [(B, "Breakfast"), (L, "Lunch"), (D, "Dinner")]:
            for meal in meal_set:
                if x[meal, i].X > 0.5:
                    print(f"    {label:<12}: {meal_name_map[meal]}")
                    plan_rows.append({
                        "day": i,
                        "day_name": DAY_NAMES[i-1],
                        "meal_type": label,
                        "meal_id": meal,
                        "meal_name": meal_name_map[meal],
                    })

    plan_df = pd.DataFrame(plan_rows)
    plan_df.to_csv("results/meal_plan.csv", index=False)
    print(f"\n  Saved meal plan -> results/meal_plan.csv")

    # ---- Per-day nutritional summary ----
    print("\n--- Daily Nutritional Summary ---")
    header = f"  {'Day':<5} {'Cal':>5} {'Prot':>5} {'Fat':>5} {'Carbs':>6} "
    header += f"{'Fiber':>5} {'Na':>5} {'Ca':>5} {'Fe':>5} {'K':>5} {'VitD':>5}"
    print(header)
    print("  " + "-" * 65)
    for i in DAYS:
        selected = [meal for meal in meal_ids if x[meal, i].X > 0.5]
        cal   = sum(a[(m, "calories")]      for m in selected)
        prot  = sum(a[(m, "protein_g")]     for m in selected)
        fat   = sum(a[(m, "fat_g")]         for m in selected)
        carbs = sum(a[(m, "carbs_g")]       for m in selected)
        fiber = sum(a[(m, "fiber_g")]       for m in selected)
        na    = sum(a[(m, "sodium_mg")]     for m in selected)
        ca    = sum(a[(m, "calcium_mg")]    for m in selected)
        fe    = sum(a[(m, "iron_mg")]       for m in selected)
        k     = sum(a[(m, "potassium_mg")]  for m in selected)
        vitd  = sum(a[(m, "vitamin_d_iu")] for m in selected)
        print(f"  {DAY_NAMES[i-1]:<5} {cal:>5.0f} {prot:>5.1f} {fat:>5.1f} "
              f"{carbs:>6.1f} {fiber:>5.1f} {na:>5.0f} {ca:>5.0f} "
              f"{fe:>5.1f} {k:>5.0f} {vitd:>5.0f}")

    # ---- Shopping list ----
    print("\n--- Shopping List ---")
    shop_rows = []
    print(f"  {'Ingredient':<35} {'Pkgs':>4} {'Pkg Size':>10} {'Cost':>7}")
    print("  " + "-" * 60)
    total_shopping = 0.0
    for j in ingredients:
        pkgs = round(y[j].X)
        if pkgs > 0:
            waste_amt = w[j].X
            cost = p[j] * pkgs
            total_shopping += cost
            ing_name = prices_df.set_index("ingredient_id").loc[j, "ingredient_name"]
            unit     = prices_df.set_index("ingredient_id").loc[j, "package_unit"]
            sz       = s[j]
            print(f"  {ing_name:<35} {pkgs:>4}  {sz}{unit:>3}    ${cost:>6.2f}")
            shop_rows.append({
                "ingredient_id": j,
                "ingredient_name": ing_name,
                "packages": pkgs,
                "package_size": sz,
                "package_unit": unit,
                "price_per_pkg": p[j],
                "total_cost": cost,
                "waste_amount": round(waste_amt, 1),
                "waste_unit": unit,
            })
    print(f"  {'TOTAL':<35} {'':>4}  {'':>10}  ${total_shopping:>6.2f}")

    shop_df = pd.DataFrame(shop_rows)
    shop_df.to_csv("results/shopping_list.csv", index=False)
    print(f"\n  Saved shopping list -> results/shopping_list.csv")
    print("=" * 65)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="CO 370 Meal Planning MIP Optimizer")
    parser.add_argument("--lam", type=float, default=0.5,
                        help="Waste penalty parameter lambda (default: 0.5)")
    parser.add_argument("--relax", action="store_true",
                        help="Use relaxed nutrient lower bounds (recommended for "
                             "food-only plans; Vit D / Mg / K are hard to meet "
                             "from this meal database alone)")
    args = parser.parse_args()

    lam  = args.lam
    nut_bounds = NUT_BOUNDS_RELAXED if args.relax else NUT_BOUNDS_STRICT

    print(f"Loading data ...")
    prices, meals, meal_ings, meal_nuts = load_data()
    ingredients, meal_ids, B, L, D, p, s, r, a = build_params(
        prices, meals, meal_ings, meal_nuts
    )
    print(f"  {len(meal_ids)} meals  |  {len(ingredients)} ingredients  |  "
          f"lambda = {lam}  |  bounds = {'relaxed' if args.relax else 'strict'}")

    print("Building model ...")
    model, x, y, w = build_model(
        ingredients, meal_ids, B, L, D, p, s, r, a,
        lam=lam, nut_bounds=nut_bounds
    )

    print("Solving ...")
    model.optimize()

    status = model.Status
    if status == GRB.OPTIMAL:
        print_and_save_results(
            model, x, y, w, ingredients, meal_ids, B, L, D,
            p, s, r, a, meals, prices, lam
        )
    elif status == GRB.INFEASIBLE:
        print("\nModel is INFEASIBLE.")
        print("Common causes with this meal database:")
        print("  - Vitamin D LB=600 IU cannot be reached from food alone "
              "(max ~378 IU/day).")
        print("  - Potassium LB=2600 mg excludes B2/B4 from any valid day.")
        print("  - Magnesium LB=310 mg requires B1 or high-Mg dinner every day.")
        print("\nRe-run with --relax to use food-achievable bounds:")
        print("  python model.py --relax")
        # Write IIS for debugging
        print("\nComputing IIS (Irreducible Infeasible Subsystem) ...")
        model.computeIIS()
        model.write("results/infeasible.ilp")
        print("  IIS written to results/infeasible.ilp")
        sys.exit(1)
    else:
        print(f"\nSolver status: {status} (no optimal solution found).")
        sys.exit(1)


if __name__ == "__main__":
    main()
