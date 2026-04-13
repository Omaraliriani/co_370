# CO 370 — Low-Cost Weekly Meal Planning Optimizer

University of Waterloo · CO 370 (Deterministic OR) · Winter 2025

A Mixed-Integer Programming (MIP) model built with **Gurobi** that plans a full week of meals (7 days x 3 meals = 21 meals) for a university student in Waterloo, ON. The model minimizes total grocery cost plus a cost-weighted waste penalty while satisfying Health Canada nutritional requirements and enforcing meal variety.

---

## Repo Structure

```
co_370/
├── data/
│   ├── ingredient_prices.csv   # 58 grocery items with prices
│   ├── meals.csv               # 48 meals (13B + 16L + 19D)
│   ├── meal_ingredients.csv    # Recipe matrix — amounts per serving
│   └── meal_nutrients.csv      # 14 nutrients per meal
│
├── results/
│   ├── meal_plan.csv           # Optimal 7-day meal plan
│   ├── shopping_list.csv       # Packages to buy + cost
│   ├── lambda_sensitivity.csv
│   ├── repetition_sensitivity.csv
│   ├── caloric_profiles.csv
│   ├── integrality_gap.csv
│   ├── shadow_prices_summary.csv
│   ├── shadow_prices_by_day.csv
│   └── shadow_prices_all_constraints.csv
│
├── scrape_prices.py        # Walmart.ca + Zehrs.ca price scraper
├── compute_nutrition.py    # Computes meal_nutrients.csv from ingredient data
├── model.py                # Main Gurobi MIP model
├── analysis.ipynb          # Sensitivity analysis (3 experiments)
├── lp_relaxation.ipynb     # LP relaxation + shadow prices
├── requirements.txt
└── README.md
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

You also need a Gurobi license (free academic license at gurobi.com).

### 2. Scrape current prices (optional)

```bash
python scrape_prices.py
```

Scrapes prices from Walmart.ca and Zehrs.ca, averages them, and falls back to the existing CSV for items that fail. The `data/ingredient_prices.csv` file already has manually verified prices, so this step is optional.

### 3. Run the MIP model

```bash
python model.py                # strict Health Canada DRI bounds
python model.py --lam 1.0      # change waste penalty
python model.py --relax         # relaxed bounds (for comparison)
```

Outputs `results/meal_plan.csv` and `results/shopping_list.csv`.

### 4. Run analysis notebooks

Open `analysis.ipynb` for sensitivity analysis (lambda sweep, repetition limits, caloric profiles).

Open `lp_relaxation.ipynb` for the LP relaxation and shadow price analysis.

---

## Data

### Ingredient Prices (`data/ingredient_prices.csv`)

**58 ingredients** across proteins, grains, dairy, produce, and pantry staples. Prices are from Walmart.ca and Zehrs.ca in the Waterloo/Kitchener area. Each row has the ingredient ID, price in CAD, package size (g or mL), category, and collection date.

The scraper (`scrape_prices.py`) can refresh prices automatically:
- **Walmart.ca**: fetches `__NEXT_DATA__` JSON from search pages, falls back to HTML parsing
- **Zehrs.ca**: uses headless Selenium (`undetected-chromedriver`), skips sponsored results

### Meal Database (`data/meals.csv` + `data/meal_ingredients.csv`)

**48 meals** that a student could realistically make, organized by type:

- **13 breakfasts (B1-B13)**: Oatmeal with Banana, Scrambled Eggs with Toast, Cereal with Milk, PB Toast, Yogurt with Banana, Pancakes, Loaded Breakfast Burrito, PB Banana Oatmeal, Egg Cheese Avocado Toast, Yogurt Granola with Berries and OJ, Oatmeal with Nuts and Orange, Eggs with Cheese Toast and OJ, Fortified Cereal with OJ and Egg
- **16 lunches (L1-L16)**: Grilled Cheese, Pasta with Tomato Sauce, Rice and Beans, Tuna Sandwich, Chicken Wrap, Ramen with Egg, Quesadilla, Burrito Bowl, Peanut Noodles, Chickpea Rice Bowl, Loaded Grilled Cheese, Salmon Rice Bowl, Sardine Toast with Spinach, Chicken Pasta with Kale, Sardine Rice with Kale, Salmon Pasta with Spinach
- **19 dinners (D1-D19)**: Chicken Stir-Fry, Spaghetti Bolognese, Baked Potato, Bean Chili, Fried Rice with Egg, Chicken Nuggets with Veggies, Lentil Soup, Beef Pasta Bake, Chicken Fried Rice Deluxe, Triple Bean Chili, Loaded Baked Potato, PB Ramen, Salmon Stir-Fry, Sardine Pasta, Beef Chili with Beans, Cheesy Chicken Rice with Broccoli, Salmon Lentil Stew, Bean and Kale Rice Bowl, Sardine Lentil Stew

`meal_ingredients.csv` defines how much of each ingredient (in g or mL) goes into one serving of each meal. We made sure to include nutrient-dense meals (salmon, sardines, fortified OJ, kale/lentil combos) to cover the harder DRI targets like vitamin D, calcium, and folate.

### Nutritional Data (`compute_nutrition.py` -> `data/meal_nutrients.csv`)

Per-100g nutrient values for all 58 ingredients are in `compute_nutrition.py`, sourced from USDA FoodData Central and the Canadian Nutrient File. Running the script multiplies by recipe amounts and produces **14 nutrients per meal**: calories, protein, fat, carbs, fiber, sugar, sodium, calcium, iron, potassium, vitamin D, B12, folate, magnesium.

---

## MIP Model (`model.py`)

### Formulation

**Sets**
- `M = B ∪ L ∪ D` — 48 meals (Breakfast, Lunch, Dinner)
- `I = {1, ..., 7}` — days of the week
- `N` — 14 tracked nutrients
- `J` — 58 ingredients

**Decision Variables**
- `x[m,i] ∈ {0,1}` — 1 if meal m is selected on day i
- `y[j] ∈ Z+` — packages of ingredient j to buy
- `w[j] >= 0` — waste of ingredient j (g or mL)

**Objective**
```
min  Σ_j  p_j · y_j  +  λ · Σ_j  (p_j / s_j) · w_j
```
First term is grocery cost, second is cost-weighted waste (converts waste to dollars using unit price p_j/s_j). Lambda (default 0.5) controls the tradeoff.

**Constraints**

| ID | Description |
|---|---|
| C1-C3 | Exactly one breakfast / lunch / dinner per day |
| C4 | Each breakfast used at most 3 times/week |
| C5 | Each lunch used at most 2 times/week |
| C6 | Each dinner used at most 2 times/week |
| C7 | No meal on consecutive days |
| C8 | Daily nutrient LB and UB (14 nutrients × 7 days) |
| C9 | Weekly calorie bounds (12,600–17,500 kcal) |
| C11 | Waste balance: w[j] = y[j]·s[j] − Σ_{m,i} r[m,j]·x[m,i] |

---

### Nutritional Bounds

#### Lower Bounds (Health Canada DRIs)

All lower bounds are the Health Canada RDA or AI for adults 19-30:

| Nutrient | LB | Source |
|---|---|---|
| Calories | 1800 kcal | EER, sedentary female 19-30 |
| Protein | 46 g | RDA |
| Fat | 44 g | AMDR lower end (20% of 2000 kcal) |
| Carbs | 225 g | AMDR lower end (45% of 2000 kcal) |
| Fiber | 25 g | AI |
| Sodium | 500 mg | Minimum physiological need |
| Calcium | 1000 mg | RDA |
| Iron | 8 mg | RDA |
| Potassium | 2600 mg | AI (NASEM 2019) |
| Vitamin D | 600 IU | RDA (NASEM 2011) |
| B12 | 2.4 mcg | RDA |
| Folate | 400 mcg DFE | RDA |
| Magnesium | 310 mg | RDA |

#### Upper Bounds

We distinguish between ULs (toxicity-based, kept strict) and AMDR/CDRR guidelines (no established toxicity, moderately relaxed):

**Relaxed (no toxicity risk):**

| Nutrient | DRI UB | Model UB | Why |
|---|---|---|---|
| Fat | 78 g | 120 g | AMDR guideline, no UL. Mediterranean diets exceed 35%. |
| Carbs | 325 g | 400 g | AMDR, no UL |
| Sugar | 50 g | 75 g | WHO guideline, no UL |
| Sodium | 2300 mg | 3000 mg | CDRR, not a UL. Avg Canadian intake ~3400 mg. |
| Magnesium | 420 mg | 600 mg | UL applies to supplements only, not food (NIH ODS) |
| Calories | 2500 kcal | 2800 kcal | Varies by activity level |

**Strict (actual toxicity risk):**

| Nutrient | UL | Risk |
|---|---|---|
| Iron | 45 mg | GI distress, organ toxicity |
| Calcium | 2500 mg | Kidney stones |
| Vitamin D | 4000 IU | Hypercalcemia |
| Folate | 1000 mcg DFE | Masks B12 deficiency |
| Potassium | 4700 mg | Cardiac arrhythmia |

---

### How We Achieved Feasibility

The initial 20-meal database was infeasible under strict DRI bounds. The main conflicts were:

1. **Vitamin D**: best possible day only reached 378 IU (need 600 IU)
2. **Calcium vs. Calories**: high-calcium meals (grilled cheese) were low-calorie; high-calorie meals (stir-fry) were low-calcium
3. **Fiber vs. Calcium**: high-fiber meals (beans, lentils) were low-calcium
4. **Magnesium**: too few high-Mg meals to cover 7 days under variety limits
5. **Folate**: most meals were too low to hit the 400 mcg floor

We checked this by enumerating all possible single-day menus. With 7 breakfasts, 8 lunches, and 6 dinners, that's 7 × 8 × 6 = 2688 possible (breakfast, lunch, dinner) combinations. For each one, we summed the nutrients and checked all 14 bounds. **Zero of the 2688 combinations satisfied all bounds simultaneously.** The worst offenders:

| Constraint | % of day-menus failing |
|---|---|
| Vitamin D ≥ 600 IU | 86.5% |
| Fiber ≥ 25 g | 66.1% |
| Sodium ≤ 2300 mg | 64.1% |
| Fat ≤ 78 g | 61.9% |
| Folate ≥ 400 mcg | 60.5% |

To fix this we:
1. Added **10 nutrient-dense ingredients** (canned salmon, sardines, fortified OJ, kale, mixed nuts, kidney beans, oranges, strawberries, frozen berries, dark chocolate)
2. Designed **16 new meals** targeting the gaps — salmon/sardine dishes for vitamin D, lentil-kale combos for folate+fiber, fortified OJ pairings for calcium+vitamin D
3. Relaxed the 6 upper bounds that are guidelines, not toxicity limits (see table above)

After these changes, the model is feasible with every daily LB matching the full Health Canada DRI.

### Results (lambda=0.5)

- **Grocery cost:** $117.41
- **Waste penalty:** $26.79
- **Total objective:** $144.20
- 27 items purchased, all 7 days meet every DRI lower bound
- Daily calories: 1881–2232 kcal
- Daily vitamin D: 662–1498 IU (all above 600 IU)
- Daily calcium: 1020–1834 mg (all above 1000 mg)

---

## Analysis

### Sensitivity Analysis (`analysis.ipynb`)

Three experiments:

1. **Lambda sweep (0 to 2)** — grocery cost stays near $117 across all lambda values. Waste drops slightly then plateaus due to structural floor (can't buy fractional packages).

2. **Repetition limits (1–5)** — how variety constraints affect cost and feasibility.

3. **Caloric profiles** — sedentary female (1600–2200), default (1800–2500), active male (2000–2800).

### LP Relaxation (`lp_relaxation.ipynb`)

Drops all integrality constraints using `Model.relax()` and extracts shadow prices.

Key findings:
- Large integrality gap — the binary meal selection structure drives most of the cost
- All daily nutrient bounds are non-binding in the LP (shadow price = 0) because the LP can mix fractional meals
- The binding constraints are structural: meal slot assignments, variety limits, waste balance

---

## Modeling Decisions

**Why cost-weighted waste?** Penalizing raw waste (Σ w_j) mixes grams of rice with mL of oil. Using (p_j/s_j) · w_j converts waste to dollars — consistent across all ingredients.

**Why LP relaxation for duals?** Gurobi only computes dual variables for LP models. We use `Model.relax()` to get shadow prices on the continuous version.

**Why relax some upper bounds?** The DRI framework has toxicity-based ULs (iron, calcium, vitamin D, folate) and guideline-based AMDRs/CDRRs (fat, carbs, sodium, sugar, magnesium from food). Only the second type was relaxed — no acute health risk for healthy adults 19-30.

---

## Dependencies

```
gurobipy
pandas
numpy
requests
beautifulsoup4
lxml
undetected-chromedriver
```

```bash
pip install -r requirements.txt
```
