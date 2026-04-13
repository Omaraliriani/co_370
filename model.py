"""
CO 370 Meal Planning MIP Model

Minimizes grocery cost + waste penalty for a 7-day, 3-meal/day plan
subject to Health Canada DRI nutritional constraints and variety limits.

Usage:
    python model.py [--lam 0.5] [--relax]
"""

import argparse
import os
import sys

import pandas as pd
import gurobipy as gp
from gurobipy import GRB

# Daily nutrient bounds from Health Canada DRIs (adults 19-30)
# LBs = RDA/AI values, UBs = UL or relaxed AMDR where safe (see README)
NUT_BOUNDS_STRICT = {
    "calories":       (1800,  2800),
    "protein_g":      (  46,   175),
    "fat_g":          (  44,   120),   # UB relaxed from AMDR 78g (no UL)
    "carbs_g":        ( 225,   400),   # UB relaxed from AMDR 325g (no UL)
    "fiber_g":        (  25,    60),
    "sugar_g":        (   0,    75),   # UB relaxed from WHO 50g (no UL)
    "sodium_mg":      ( 500,  3000),   # UB relaxed from CDRR 2300mg (no UL)
    "calcium_mg":     (1000,  2500),
    "iron_mg":        (   8,    45),
    "potassium_mg":   (2600,  4700),
    "vitamin_d_iu":   ( 600,  4000),
    "b12_mcg":        ( 2.4,   200),
    "folate_mcg_dfe": ( 400,  1000),
    "magnesium_mg":   ( 310,   600),   # UB relaxed (UL is supplements only)
}

# Relaxed bounds for comparison — ~50-70% of DRI targets
NUT_BOUNDS_RELAXED = {
    "calories":       (1800, 2800),
    "protein_g":      ( 35,   200),
    "fat_g":          ( 15,   120),
    "carbs_g":        (120,   450),
    "fiber_g":        ( 10,    80),
    "sugar_g":        (  0,    80),
    "sodium_mg":      (300,  3500),
    "calcium_mg":     (400,  2500),
    "iron_mg":        (  4,    45),
    "potassium_mg":   (900,  4700),
    "vitamin_d_iu":   ( 30,  4000),
    "b12_mcg":        (0.5,   200),
    "folate_mcg_dfe": ( 80,  1200),
    "magnesium_mg":   ( 50,   500),
}

NUTRIENTS = list(NUT_BOUNDS_STRICT.keys())
DAYS = list(range(1, 8))


def load_data():
    """Read the four CSV data files."""
    prices    = pd.read_csv("data/ingredient_prices.csv")
    meals     = pd.read_csv("data/meals.csv")
    meal_ings = pd.read_csv("data/meal_ingredients.csv")
    meal_nuts = pd.read_csv("data/meal_nutrients.csv")
    return prices, meals, meal_ings, meal_nuts


def build_params(prices, meals, meal_ings, meal_nuts):
    """Convert DataFrames into the dicts/lists the model needs."""
    ingredients = prices["ingredient_id"].tolist()
    meal_ids    = meals["meal_id"].tolist()
    B = meals[meals["meal_type"] == "B"]["meal_id"].tolist()
    L = meals[meals["meal_type"] == "L"]["meal_id"].tolist()
    D = meals[meals["meal_type"] == "D"]["meal_id"].tolist()

    p = prices.set_index("ingredient_id")["price_cad"].to_dict()    # price per package
    s = prices.set_index("ingredient_id")["package_size"].to_dict()  # package size (g/mL)

    # recipe matrix: r[(meal, ingredient)] = amount needed
    r = {}
    for _, row in meal_ings.iterrows():
        r[(row["meal_id"], row["ingredient_id"])] = float(row["amount_needed"])

    # nutrient matrix: a[(meal, nutrient)] = nutrient amount
    a = {}
    for _, row in meal_nuts.iterrows():
        for n in NUTRIENTS:
            a[(row["meal_id"], n)] = float(row[n])

    return ingredients, meal_ids, B, L, D, p, s, r, a


def build_model(ingredients, meal_ids, B, L, D, p, s, r, a,
                lam=0.5, nut_bounds=None):
    """Build and return the Gurobi MIP model."""
    if nut_bounds is None:
        nut_bounds = NUT_BOUNDS_STRICT

    m = gp.Model("MealPlanner")
    m.setParam("OutputFlag", 1)

    # Decision variables
    x = m.addVars(meal_ids, DAYS, vtype=GRB.BINARY, name="x")       # meal selection
    y = m.addVars(ingredients, vtype=GRB.INTEGER, lb=0, name="y")    # packages to buy
    w = m.addVars(ingredients, vtype=GRB.CONTINUOUS, lb=0, name="w") # waste

    # Objective: min grocery cost + lambda * cost-weighted waste
    grocery_cost = gp.quicksum(p[j] * y[j] for j in ingredients)
    waste_cost   = gp.quicksum((p[j] / s[j]) * w[j] for j in ingredients)
    m.setObjective(grocery_cost + lam * waste_cost, GRB.MINIMIZE)

    # C1-C3: exactly one breakfast, lunch, dinner per day
    for i in DAYS:
        m.addConstr(gp.quicksum(x[b, i] for b in B) == 1, name=f"C1_d{i}")
        m.addConstr(gp.quicksum(x[l, i] for l in L) == 1, name=f"C2_d{i}")
        m.addConstr(gp.quicksum(x[d, i] for d in D) == 1, name=f"C3_d{i}")

    # C4-C6: repetition limits per week
    for b in B:
        m.addConstr(gp.quicksum(x[b, i] for i in DAYS) <= 3, name=f"C4_{b}")
    for l in L:
        m.addConstr(gp.quicksum(x[l, i] for i in DAYS) <= 2, name=f"C5_{l}")
    for d in D:
        m.addConstr(gp.quicksum(x[d, i] for i in DAYS) <= 2, name=f"C6_{d}")

    # C7: no meal on consecutive days
    for meal in meal_ids:
        for i in range(1, 7):
            m.addConstr(x[meal, i] + x[meal, i + 1] <= 1,
                        name=f"C7_{meal}_d{i}")

    # C8: daily nutrient LB and UB
    for i in DAYS:
        for n in NUTRIENTS:
            lb, ub = nut_bounds[n]
            daily = gp.quicksum(a[(meal, n)] * x[meal, i] for meal in meal_ids)
            m.addConstr(daily >= lb, name=f"C8_lb_{n}_d{i}")
            m.addConstr(daily <= ub, name=f"C8_ub_{n}_d{i}")

    # C9: weekly calorie bounds
    weekly_cal = gp.quicksum(
        a[(meal, "calories")] * x[meal, i]
        for meal in meal_ids for i in DAYS
    )
    m.addConstr(weekly_cal >= 7 * 1800, name="C9_lb")
    m.addConstr(weekly_cal <= 7 * 2500, name="C9_ub")

    # C11: waste balance — w[j] = packages bought * size - total usage
    for j in ingredients:
        total_usage = gp.quicksum(
            r[(meal, j)] * x[meal, i]
            for meal in meal_ids for i in DAYS
            if (meal, j) in r
        )
        m.addConstr(w[j] == y[j] * s[j] - total_usage, name=f"C11_{j}")

    return m, x, y, w


DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def print_and_save_results(m, x, y, w, ingredients, meal_ids, B, L, D,
                            p, s, r, a, meals_df, prices_df, lam):
    """Print the optimal plan and save CSVs."""
    os.makedirs("results", exist_ok=True)

    grocery_total = sum(p[j] * round(y[j].X) for j in ingredients)
    waste_total   = sum((p[j] / s[j]) * w[j].X for j in ingredients)

    print(f"\nObjective: ${m.ObjVal:.2f}")
    print(f"  Grocery cost: ${grocery_total:.2f}")
    print(f"  Waste penalty (lam={lam}): ${lam * waste_total:.2f}")

    # Meal plan
    meal_name = meals_df.set_index("meal_id")["meal_name"].to_dict()
    plan_rows = []

    for i in DAYS:
        print(f"\n  {DAY_NAMES[i-1]} (Day {i})")
        for meal_set, label in [(B, "Breakfast"), (L, "Lunch"), (D, "Dinner")]:
            for ml in meal_set:
                if x[ml, i].X > 0.5:
                    print(f"    {label:<12}: {meal_name[ml]}")
                    plan_rows.append({
                        "day": i, "day_name": DAY_NAMES[i-1],
                        "meal_type": label, "meal_id": ml,
                        "meal_name": meal_name[ml],
                    })

    pd.DataFrame(plan_rows).to_csv("results/meal_plan.csv", index=False)

    # Daily nutrition check
    
    hdr = f"  {'Day':<5} {'Cal':>5} {'Prot':>5} {'Fat':>5} {'Carbs':>6} "
    hdr += f"{'Fiber':>5} {'Na':>5} {'Ca':>5} {'Fe':>5} {'K':>5} {'VitD':>5}"
    
    for i in DAYS:
        sel = [ml for ml in meal_ids if x[ml, i].X > 0.5]
        vals = {n: sum(a[(ml, n)] for ml in sel) for n in NUTRIENTS}
        print(f"  {DAY_NAMES[i-1]:<5} {vals['calories']:>5.0f} "
              f"{vals['protein_g']:>5.1f} {vals['fat_g']:>5.1f} "
              f"{vals['carbs_g']:>6.1f} {vals['fiber_g']:>5.1f} "
              f"{vals['sodium_mg']:>5.0f} {vals['calcium_mg']:>5.0f} "
              f"{vals['iron_mg']:>5.1f} {vals['potassium_mg']:>5.0f} "
              f"{vals['vitamin_d_iu']:>5.0f}")

    # Shopping list
    print("\n--- Shopping List ---")
    shop_rows = []
    total = 0.0
    print(f"  {'Ingredient':<35} {'Pkgs':>4} {'Pkg Size':>10} {'Cost':>7}")
    print("  " + "-" * 60)
    for j in ingredients:
        pkgs = round(y[j].X)
        if pkgs > 0:
            cost = p[j] * pkgs
            total += cost
            name = prices_df.set_index("ingredient_id").loc[j, "ingredient_name"]
            unit = prices_df.set_index("ingredient_id").loc[j, "package_unit"]
            print(f"  {name:<35} {pkgs:>4}  {s[j]}{unit:>3}    ${cost:>6.2f}")
            shop_rows.append({
                "ingredient_id": j, "ingredient_name": name,
                "packages": pkgs, "package_size": s[j],
                "package_unit": unit, "price_per_pkg": p[j],
                "total_cost": cost, "waste_amount": round(w[j].X, 1),
                "waste_unit": unit,
            })
    

    pd.DataFrame(shop_rows).to_csv("results/shopping_list.csv", index=False)


def main():
    parser = argparse.ArgumentParser(description="CO 370 Meal Planner")
    parser.add_argument("--lam", type=float, default=0.5,
                        help="Waste penalty lambda (default: 0.5)")
    parser.add_argument("--relax", action="store_true",
                        help="Use relaxed nutrient bounds")
    args = parser.parse_args()

    lam = args.lam
    nut_bounds = NUT_BOUNDS_RELAXED if args.relax else NUT_BOUNDS_STRICT

    prices, meals, meal_ings, meal_nuts = load_data()
    ingredients, meal_ids, B, L, D, p, s, r, a = build_params(
        prices, meals, meal_ings, meal_nuts
    )
    print(f"{len(meal_ids)} meals | {len(ingredients)} ingredients | "
          f"lam={lam} | {'relaxed' if args.relax else 'strict'} bounds")

    model, x, y, w = build_model(
        ingredients, meal_ids, B, L, D, p, s, r, a,
        lam=lam, nut_bounds=nut_bounds
    )
    model.optimize()

    if model.Status == GRB.OPTIMAL:
        print_and_save_results(
            model, x, y, w, ingredients, meal_ids, B, L, D,
            p, s, r, a, meals, prices, lam
        )
    elif model.Status == GRB.INFEASIBLE:
        print("\nModel is INFEASIBLE. Try --relax for looser bounds.")
        model.computeIIS()
        model.write("results/infeasible.ilp")
        sys.exit(1)
    else:
        print(f"\nSolver status: {model.Status}")
        sys.exit(1)


if __name__ == "__main__":
    main()
