"""
analysis.py
-----------
Phase 3A: Sensitivity analysis for the CO 370 meal planning MIP.

Experiments:
  1. Lambda sweep (waste penalty 0 -> 2): cost vs waste tradeoff
  2. Repetition limits (max uses per lunch/dinner, 1 -> 5): cost vs variety
  3. Caloric profiles: sedentary female (1600-2200) vs active male (2000-2800)

All plots saved to results/plots/.

Usage:
    python analysis.py
"""

import os
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import gurobipy as gp
from gurobipy import GRB

from model import load_data, build_params, build_model, NUT_BOUNDS_RELAXED, DAYS

os.makedirs("results/plots", exist_ok=True)


QUIET = {"OutputFlag": 0, "LogToConsole": 0}


# Helper: solve and return (grocery_cost, waste_cost_raw, obj, status)
def solve_instance(ingredients, meal_ids, B, L, D, p, s, r, a,
                   lam=0.5, nut_bounds=None,
                   rep_b=3, rep_l=2, rep_d=2,
                   cal_lb=1800, cal_ub=2500):
    """
    Build and solve one MIP instance.  Returns a dict with:
        status, obj, grocery_cost, waste_cost_raw, x_vals, y_vals, w_vals
    """
    if nut_bounds is None:
        nut_bounds = NUT_BOUNDS_RELAXED

    # Override calorie bounds
    bounds = dict(nut_bounds)
    bounds["calories"] = (cal_lb, cal_ub)

    m, x, y, w = build_model(
        ingredients, meal_ids, B, L, D, p, s, r, a,
        lam=lam, nut_bounds=bounds
    )

    # Override repetition limits
    for constr in m.getConstrs():
        name = constr.ConstrName
        if name.startswith("C4_"):
            constr.RHS = rep_b
        elif name.startswith("C5_"):
            constr.RHS = rep_l
        elif name.startswith("C6_"):
            constr.RHS = rep_d

    for k, v in QUIET.items():
        m.setParam(k, v)

    m.optimize()

    if m.Status != GRB.OPTIMAL:
        return {"status": m.Status}

    grocery = sum(p[j] * round(y[j].X) for j in ingredients)
    waste_raw = sum((p[j] / s[j]) * w[j].X for j in ingredients)

    return {
        "status": GRB.OPTIMAL,
        "obj": m.ObjVal,
        "grocery_cost": grocery,
        "waste_cost_raw": waste_raw,
        "waste_penalty": lam * waste_raw,
    }

# Experiment 1: Lambda sweep

def experiment_lambda(ingredients, meal_ids, B, L, D, p, s, r, a):
    lambdas = [0, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0]
    rows = []
    print("  Lambda sweep ...")
    for lam in lambdas:
        res = solve_instance(ingredients, meal_ids, B, L, D, p, s, r, a, lam=lam)
        if res["status"] != GRB.OPTIMAL:
            print(f"    lambda={lam}: INFEASIBLE/no solution")
            continue
        rows.append({
            "lambda": lam,
            "grocery_cost": res["grocery_cost"],
            "waste_cost_raw": res["waste_cost_raw"],
            "waste_penalty": res["waste_penalty"],
            "total_obj": res["obj"],
        })
        print(f"    lambda={lam:.2f}: grocery=${res['grocery_cost']:.2f}  "
              f"waste(raw)=${res['waste_cost_raw']:.2f}  "
              f"obj=${res['obj']:.2f}")

    df = pd.DataFrame(rows)

    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    fig.suptitle("Sensitivity to Waste Penalty Parameter (lambda)", fontsize=13)

    ax = axes[0]
    ax.plot(df["lambda"], df["grocery_cost"], "o-", color="steelblue", linewidth=2)
    ax.set_xlabel("lambda")
    ax.set_ylabel("Total Grocery Cost ($)")
    ax.set_title("Grocery Cost vs lambda")
    ax.grid(True, alpha=0.3)

    ax = axes[1]
    ax.plot(df["lambda"], df["waste_cost_raw"], "s-", color="darkorange", linewidth=2)
    ax.set_xlabel("lambda")
    ax.set_ylabel("Raw Waste Cost ($)")
    ax.set_title("Waste ($ value) vs lambda")
    ax.grid(True, alpha=0.3)

    ax = axes[2]
    ax.plot(df["grocery_cost"], df["waste_cost_raw"], "D-", color="purple", linewidth=2)
    for _, row in df.iterrows():
        ax.annotate(f"l={row['lambda']:.2f}",
                    (row["grocery_cost"], row["waste_cost_raw"]),
                    textcoords="offset points", xytext=(4, 4), fontsize=7)
    ax.set_xlabel("Grocery Cost ($)")
    ax.set_ylabel("Waste ($)")
    ax.set_title("Cost-Waste Tradeoff Curve")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    path = "results/plots/lambda_sensitivity.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved -> {path}")
    return df


# Experiment 2: Repetition limits

def experiment_repetition(ingredients, meal_ids, B, L, D, p, s, r, a):
    rep_limits = [1, 2, 3, 4, 5]
    rows = []
    print("  Repetition limit sweep (lunch & dinner) ...")
    for rep in rep_limits:
        # Breakfast limit stays at 3; vary lunch & dinner together
        res = solve_instance(
            ingredients, meal_ids, B, L, D, p, s, r, a,
            lam=0.5, rep_b=3, rep_l=rep, rep_d=rep
        )
        if res["status"] != GRB.OPTIMAL:
            # If rep=1 with 7 days and only 7 lunch options = each used once: feasible
            # Should be fine for rep >= 1 given 7 lunch options
            print(f"    rep={rep}: INFEASIBLE")
            rows.append({"rep_limit": rep, "grocery_cost": None, "waste_cost_raw": None})
            continue
        rows.append({
            "rep_limit": rep,
            "grocery_cost": res["grocery_cost"],
            "waste_cost_raw": res["waste_cost_raw"],
        })
        print(f"    rep={rep}: grocery=${res['grocery_cost']:.2f}  "
              f"waste=${res['waste_cost_raw']:.2f}")

    df = pd.DataFrame(rows).dropna()

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    fig.suptitle("Sensitivity to Meal Repetition Limit (Lunch & Dinner)", fontsize=13)

    ax = axes[0]
    ax.plot(df["rep_limit"], df["grocery_cost"], "o-", color="steelblue", linewidth=2,
            marker="o", markersize=8)
    ax.set_xlabel("Max Repetitions per Meal (Lunch & Dinner)")
    ax.set_ylabel("Grocery Cost ($)")
    ax.set_title("Grocery Cost vs Repetition Limit")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.grid(True, alpha=0.3)

    ax = axes[1]
    ax.plot(df["rep_limit"], df["waste_cost_raw"], "s-", color="darkorange", linewidth=2,
            marker="s", markersize=8)
    ax.set_xlabel("Max Repetitions per Meal (Lunch & Dinner)")
    ax.set_ylabel("Waste Cost ($)")
    ax.set_title("Waste vs Repetition Limit")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    path = "results/plots/repetition_sensitivity.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved -> {path}")
    return df


# Experiment 3: Caloric profiles
def experiment_caloric_profiles(ingredients, meal_ids, B, L, D, p, s, r, a):
    profiles = [
        ("Sedentary Female\n(1600-2200 kcal/day)", 1600, 2200),
        ("Default\n(1800-2500 kcal/day)",           1800, 2500),
        ("Active Male\n(2000-2800 kcal/day)",        2000, 2800),
    ]
    rows = []
    print("  Caloric profile comparison ...")
    for label, lb, ub in profiles:
        res = solve_instance(
            ingredients, meal_ids, B, L, D, p, s, r, a,
            lam=0.5, cal_lb=lb, cal_ub=ub
        )
        status_str = "optimal" if res["status"] == GRB.OPTIMAL else "infeasible"
        gc = res.get("grocery_cost", None)
        wc = res.get("waste_cost_raw", None)
        rows.append({
            "profile": label.replace("\n", " "),
            "cal_lb": lb,
            "cal_ub": ub,
            "grocery_cost": gc,
            "waste_cost_raw": wc,
            "status": status_str,
        })
        if gc is not None:
            print(f"    {label!r}: grocery=${gc:.2f}  waste=${wc:.2f}")
        else:
            print(f"    {label!r}: {status_str}")

    df = pd.DataFrame(rows)

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    fig.suptitle("Cost Comparison Across Caloric Profiles", fontsize=13)

    optimal = df[df["status"] == "optimal"]
    labels  = [p.replace("\\n", "\n") for p in optimal["profile"]]
    x = range(len(optimal))

    ax = axes[0]
    bars = ax.bar(x, optimal["grocery_cost"], color=["#4C72B0", "#DD8452", "#55A868"],
                  edgecolor="white", linewidth=1.2)
    ax.bar_label(bars, fmt="$%.2f", padding=3, fontsize=9)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("Grocery Cost ($)")
    ax.set_title("Grocery Cost by Profile")
    ax.grid(True, axis="y", alpha=0.3)

    ax = axes[1]
    bars = ax.bar(x, optimal["waste_cost_raw"], color=["#4C72B0", "#DD8452", "#55A868"],
                  edgecolor="white", linewidth=1.2)
    ax.bar_label(bars, fmt="$%.2f", padding=3, fontsize=9)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("Waste Cost ($)")
    ax.set_title("Food Waste by Profile")
    ax.grid(True, axis="y", alpha=0.3)

    plt.tight_layout()
    path = "results/plots/caloric_profiles.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved -> {path}")
    return df


# Main


def main():
    print("Loading data ...")
    prices, meals, meal_ings, meal_nuts = load_data()
    ingredients, meal_ids, B, L, D, p, s, r, a = build_params(
        prices, meals, meal_ings, meal_nuts
    )

    print("\n[Experiment 1] Lambda sensitivity")
    df_lam = experiment_lambda(ingredients, meal_ids, B, L, D, p, s, r, a)
    df_lam.to_csv("results/lambda_sensitivity.csv", index=False)

    print("\n[Experiment 2] Repetition limit sensitivity")
    df_rep = experiment_repetition(ingredients, meal_ids, B, L, D, p, s, r, a)
    df_rep.to_csv("results/repetition_sensitivity.csv", index=False)

    print("\n[Experiment 3] Caloric profile comparison")
    df_cal = experiment_caloric_profiles(ingredients, meal_ids, B, L, D, p, s, r, a)
    df_cal.to_csv("results/caloric_profiles.csv", index=False)

    print("\nAll experiments complete.  Plots in results/plots/")


if __name__ == "__main__":
    main()
