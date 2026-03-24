# CO 370 — Low-Cost Weekly Meal Planning Optimizer

University of Waterloo · CO 370 (Deterministic OR) · Winter 2025

A Mixed-Integer Programming (MIP) model built with **Gurobi** that plans a full week of meals (7 days × 3 meals = 21 meals) for a university student in Waterloo, ON. The model minimizes total grocery cost plus a cost-weighted waste penalty while satisfying nutritional requirements and enforcing meal variety.

---

## Repo Structure

```
co_370/
├── data/
│   ├── ingredient_prices.csv   # 42 grocery items with Walmart.ca Waterloo prices
│   ├── meals.csv               # 20 meals (6B + 7L + 7D)
│   ├── meal_ingredients.csv    # Recipe matrix r[m,j] — amounts per serving
│   └── meal_nutrients.csv      # 14 nutrients per meal (computed by compute_nutrition.py)
│
├── results/
│   ├── meal_plan.csv           # Optimal 7-day meal plan
│   ├── shopping_list.csv       # Packages to buy + cost per item
│   ├── lambda_sensitivity.csv  # Cost/waste vs lambda
│   ├── repetition_sensitivity.csv
│   ├── caloric_profiles.csv
│   ├── integrality_gap.csv     # MIP vs LP objective comparison
│   ├── shadow_prices_summary.csv
│   ├── shadow_prices_by_day.csv
│   ├── shadow_prices_all_constraints.csv
│   └── plots/
│       ├── lambda_sensitivity.png
│       ├── repetition_sensitivity.png
│       ├── caloric_profiles.png
│       └── shadow_prices.png
│
├── scrape_prices.py        # Phase 1A — Walmart.ca scraper (with fallback)
├── compute_nutrition.py    # Phase 1C — Computes meal_nutrients.csv from ingredients
├── build_meal_db.py        # Validates all Phase 1 data files for consistency
├── model.py                # Phase 2  — Main Gurobi MIP model
├── analysis.py             # Phase 3A — Sensitivity analysis + plots
├── lp_relaxation.py        # Phase 3B — LP relaxation + shadow prices
├── requirements.txt
└── README.md
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

You also need a Gurobi license (free academic license available at gurobi.com).

### 2. Validate the data

```bash
python build_meal_db.py
```

Checks that all meal IDs, ingredient IDs, and units are consistent across the three data files. Should report zero errors.

### 3. Run the MIP model

```bash
# With relaxed nutrient bounds (recommended — see Feasibility section below)
python model.py --relax

# Vary the waste penalty parameter (default lambda=0.5)
python model.py --relax --lam 1.0

# See what happens with strict Health Canada DRI bounds (will be infeasible)
python model.py
```

Outputs: `results/meal_plan.csv`, `results/shopping_list.csv`, printed plan + shopping list.

### 4. Run sensitivity analysis

```bash
python analysis.py
```

Runs three experiments (lambda sweep, repetition limits, caloric profiles) and saves plots to `results/plots/`.

### 5. Run LP relaxation and shadow price analysis

```bash
python lp_relaxation.py
```

Relaxes all binary/integer variables, solves the LP, and reports shadow prices on nutritional and structural constraints.

---

## Phase 1 — Data Collection

### 1A · Ingredient Prices (`scrape_prices.py` → `data/ingredient_prices.csv`)

`scrape_prices.py` attempts to hit the Walmart.ca JSON search API with the store location set to Waterloo, ON (postal code N2L). In practice, Walmart.ca's anti-bot protection blocks automated scraping, so prices were manually collected by browsing the Waterloo store pages in March 2025.

**42 ingredients** are included across categories: proteins, grains, dairy, produce, and pantry staples. Each row has:

| Column | Description |
|---|---|
| `ingredient_id` | Snake-case key used throughout the codebase |
| `price_cad` | Price per package in CAD (Walmart.ca Waterloo, March 2025) |
| `package_size` | Size of one package (in grams or mL) |
| `package_unit` | `g` for solids, `mL` for liquids — **units must match `meal_ingredients.csv`** |

To re-attempt scraping (with StatCan validation):
```bash
python scrape_prices.py --validate-statcan
```

### 1B · Meal Database (`data/meals.csv` + `data/meal_ingredients.csv`)

**20 meals** covering realistic student eating:
- **6 breakfasts**: Oatmeal with Banana, Scrambled Eggs with Toast, Cereal with Milk, Peanut Butter Toast, Yogurt with Banana, Pancakes with Butter
- **7 lunches**: Grilled Cheese, Pasta with Tomato Sauce, Rice and Beans, Tuna Sandwich, Chicken Wrap, Ramen with Egg, Quesadilla with Salsa
- **7 dinners**: Chicken Stir-Fry with Rice, Spaghetti Bolognese, Baked Potato, Bean Chili, Fried Rice with Egg, Chicken Nuggets with Veggies, Lentil Soup

`meal_ingredients.csv` defines the recipe matrix **r[m,j]** — the amount of ingredient `j` (in grams or mL) required for one serving of meal `m`. Units are standardized to match the `package_unit` in `ingredient_prices.csv` so that the waste balance constraint works correctly.

### 1C · Nutritional Data (`compute_nutrition.py` → `data/meal_nutrients.csv`)

Per-100g nutritional values for all 42 ingredients are embedded in `compute_nutrition.py` (sourced from USDA FoodData Central / Canadian Nutrient File). The script multiplies by recipe amounts and sums across ingredients to produce **14 nutrients per meal**:

calories, protein, fat, carbohydrates, fiber, sugar, sodium, calcium, iron, potassium, vitamin D, B12, folate, magnesium

To regenerate:
```bash
python compute_nutrition.py
```

---

## Phase 2 — MIP Model (`model.py`)

### Formulation

**Sets**
- `M = B ∪ L ∪ D` — 20 meals partitioned into Breakfast, Lunch, Dinner
- `I = {1, …, 7}` — days of the week
- `N` — 14 tracked nutrients
- `J` — 42 ingredients

**Decision Variables**
- `x[m,i] ∈ {0,1}` — 1 if meal `m` is selected on day `i`
- `y[j] ∈ ℤ+` — number of packages of ingredient `j` to purchase
- `w[j] ≥ 0` — waste of ingredient `j` (in grams or mL)

**Objective**
```
min  Σ_j  p_j · y_j  +  λ · Σ_j  (p_j / s_j) · w_j
```
- First term: total grocery cost
- Second term: cost-weighted waste (waste measured in dollars, not raw units)
- `λ` (default 0.5) controls the cost-waste tradeoff

**Constraints**

| ID | Description |
|---|---|
| C1–C3 | Exactly one breakfast / lunch / dinner per day |
| C4 | Each breakfast meal used at most 3 times per week |
| C5 | Each lunch meal used at most 2 times per week |
| C6 | Each dinner meal used at most 2 times per week |
| C7 | No meal repeated on consecutive days |
| C8 | Daily nutrient lower and upper bounds (14 nutrients × 7 days) |
| C9 | Weekly calorie bounds (12,600–17,500 kcal) |
| C11 | Waste balance: `w[j] = y[j]·s[j] − Σ_{m,i} r[m,j]·x[m,i]` |

### Feasibility and the `--relax` Flag

The strict Health Canada DRI bounds are **jointly infeasible** with this meal database due to two structural conflicts:

1. **Calcium ≥ 1000 mg + Calories ≥ 1800 kcal per day** — The calcium-rich meals (grilled cheese, quesadilla, baked potato) are too low-calorie; the high-calorie dinners (stir-fry, bolognese, fried rice) are low-calcium. The best achievable combination gives ~988 mg Ca at only ~1546 kcal, which satisfies neither constraint simultaneously.

2. **Fiber ≥ 25 g + Calcium ≥ 1000 mg per day** — High-fiber meals (beans, lentils, oats) have low calcium; high-calcium meals (dairy) have low fiber. These constraints cannot be met simultaneously from this meal database.

Additional note: B5 (Yogurt with Banana, 229 kcal) is excluded by the calorie floor — `max(B5 + any L + any D) = 1772 kcal < 1800`.

Running `python model.py` without `--relax` will produce an infeasible result and write an IIS report to `results/infeasible.ilp`. The `--relax` flag uses bounds at approximately 40–70% of DRI values — still nutritionally meaningful for a food-only student diet without supplementation. These constraint conflicts are discussed in the report as a modeling finding.

### Optimal Results (λ=0.5, relaxed bounds)

- **Grocery cost:** $99.75
- **Waste penalty:** $31.63 (raw waste value $63.26)
- **Total objective:** $131.38
- 25 distinct grocery items purchased (1 package each)

---

## Phase 3 — Analysis

### 3A · Sensitivity Analysis (`analysis.py`)

Three experiments, all plots saved to `results/plots/`:

**Experiment 1 — Lambda sweep (λ = 0 → 2)**
Grocery cost stays near $99 across all λ values. Waste drops slightly at low λ (from $65.71 at λ=0 to $63.26 at λ=0.5) then plateaus. The model hits a structural floor: buying fewer packages than needed is infeasible, so waste reduction beyond a threshold cannot occur without changing the meal plan.

**Experiment 2 — Repetition limits (1–5 uses per lunch/dinner)**
Cost and waste are identical across all repetition limits tested. The optimal plan already uses each meal at most twice, so loosening or tightening the cap does not change the solution.

**Experiment 3 — Caloric profiles**
| Profile | Cal/day range | Grocery Cost | Waste |
|---|---|---|---|
| Sedentary female | 1600–2200 | $88.78 | $57.98 |
| Default | 1800–2500 | $99.75 | $63.26 |
| Active male | 2000–2800 | infeasible | — |

The active male profile (min 2000 kcal/day) is infeasible because no single B+L+D combination in the database reliably exceeds 2000 kcal/day under the variety and no-consecutive constraints.

### 3B · LP Relaxation & Shadow Prices (`lp_relaxation.py`)

Uses `Model.relax()` (the correct Gurobi API) to create a pure LP by dropping all integrality constraints.

**Integrality gap: 398%**
- MIP objective: $131.38
- LP objective: $26.37
- Gap: $105.01

This extremely large gap means that the binary structure of meal selection (must pick exactly one complete meal per slot per day) accounts for nearly 80% of total cost. A "fractional diet" (eating 0.3 of one meal and 0.7 of another) would cost only $26/week.

**Shadow prices — nutritional constraints (C8): all zero**
In the LP relaxation, every daily nutrient bound is non-binding. The LP can trivially satisfy all 14 nutrient constraints by mixing fractional meals optimally. This means **nutritional requirements are not cost drivers in the LP**.

**Shadow prices — structural constraints: non-zero**
The binding constraints in the LP are the structural ones:

| Constraint | Avg |π| | Interpretation |
|---|---|---|
| C1/C2/C3 (meal slot) | ~$0.31 | Cost of committing one meal per slot per day |
| C5 (lunch variety, max 2) | $0.85 max | Tightest variety constraint |
| C6 (dinner variety, max 2) | $0.77 max | Second tightest variety constraint |
| C9_lb (weekly calorie floor) | $0.0025/kcal | Calorie floor is slightly binding |
| C11 (waste balance) | $0.007 avg | All waste balance constraints bind |
| C7 (no-consecutive) | $0.00 | No-consecutive rule is not binding in LP |

---

## Key Modeling Decisions

**Why no preference or difficulty scores?**
The meal database was pre-curated to include only meals students would realistically make and eat. Adding preference weights would introduce subjective parameters with no principled calibration. The feasibility of each meal is implicitly guaranteed by the curated list.

**Why cost-weighted waste (not raw grams)?**
Penalizing `Σ w_j` directly mixes incompatible units (grams of rice vs. mL of oil vs. grams of cheese). The updated objective uses `(p_j / s_j) · w_j` — the unit price times waste amount — giving waste a consistent dollar value across all ingredients.

**Why LP relaxation for duals (not MIP duals)?**
Gurobi does not compute dual variables for MIP models (only LP duals are meaningful). The LP relaxation obtained via `Model.relax()` gives shadow prices that reflect the continuous cost structure.

---

## Dependencies

```
gurobipy    # Gurobi Python API (requires license)
pandas
matplotlib
seaborn
numpy
requests
beautifulsoup4
selenium    # optional, for JS-rendered scraping
```

Install with:
```bash
pip install -r requirements.txt
```
