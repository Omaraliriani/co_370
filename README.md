# CO 370 — Low-Cost Weekly Meal Planning Optimizer

University of Waterloo · CO 370 (Deterministic OR) · Winter 2025

A Mixed-Integer Programming (MIP) model built with **Gurobi** that plans a full week of meals (7 days x 3 meals = 21 meals) for a university student in Waterloo, ON. The model minimizes total grocery cost plus a cost-weighted waste penalty while satisfying Health Canada nutritional requirements and enforcing meal variety.

---

## Repo Structure

```
co_370/
├── data/
│   ├── ingredient_prices.csv   # 58 grocery items — scraped from Walmart.ca & Zehrs.ca
│   ├── meals.csv               # 48 meals (13B + 16L + 19D)
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
├── scrape_prices.py        # Phase 1A — Walmart.ca API + Zehrs.ca Selenium scraper
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

### 2. Scrape current prices

```bash
python scrape_prices.py
```

Scrapes prices from **Walmart.ca** (via API / `__NEXT_DATA__` JSON) and **Zehrs.ca** (via Selenium with `undetected-chromedriver`). Averages prices from both stores. Falls back to the existing CSV for items that fail to scrape. See [Price Scraping](#1a--ingredient-prices) below.

### 3. Validate the data

```bash
python build_meal_db.py
```

Checks that all meal IDs, ingredient IDs, and units are consistent across the three data files. Should report zero errors.

### 4. Run the MIP model

```bash
# Default: strict Health Canada DRI lower bounds with safe upper bounds
python model.py

# Vary the waste penalty parameter (default lambda=0.5)
python model.py --lam 1.0

# Fully relaxed bounds (reduces all LBs — for comparison only)
python model.py --relax
```

Outputs: `results/meal_plan.csv`, `results/shopping_list.csv`, printed plan + shopping list.

### 5. Run sensitivity analysis

```bash
python analysis.py
```

Runs three experiments (lambda sweep, repetition limits, caloric profiles) and saves plots to `results/plots/`.

### 6. Run LP relaxation and shadow price analysis

```bash
python lp_relaxation.py
```

Relaxes all binary/integer variables, solves the LP, and reports shadow prices on nutritional and structural constraints.

---

## Phase 1 — Data Collection

### 1A · Ingredient Prices (`scrape_prices.py` -> `data/ingredient_prices.csv`)

`scrape_prices.py` scrapes real grocery prices from two stores in the Waterloo/Kitchener area:

| Store | Method | Notes |
|---|---|---|
| **Walmart.ca** | `requests` + `__NEXT_DATA__` JSON parsing | Fetches the Next.js SSR data embedded in search result pages. Falls back to HTML parsing if JSON unavailable. No browser needed. |
| **Zehrs.ca** | Selenium via `undetected-chromedriver` (headless) | Zehrs uses Chakra UI / React with lazy-loaded content. The scraper skips sponsored products (`source=sptd` in URL) and auto-restarts the browser every 10 requests to avoid session timeouts. |

For each ingredient, the scraper:
1. Searches both store websites
2. Extracts the price and package size/unit from the first non-sponsored result
3. Averages the prices from both stores (or uses one if only one succeeded)
4. Falls back to the existing CSV for items that neither store returned

**58 ingredients** are included across categories: proteins, grains, dairy, produce, and pantry staples. Each row has:

| Column | Description |
|---|---|
| `ingredient_id` | Snake-case key used throughout the codebase |
| `price_cad` | Price per package in CAD (averaged from Walmart + Zehrs) |
| `package_size` | Size of one package (in grams or mL) |
| `package_unit` | `g` for solids, `mL` for liquids — **units must match `meal_ingredients.csv`** |
| `source_url` | URL(s) used to scrape the price |
| `date_collected` | Date prices were last scraped |

To re-scrape prices:
```bash
python scrape_prices.py
```

### 1B · Meal Database (`data/meals.csv` + `data/meal_ingredients.csv`)

**48 meals** covering realistic student eating, including nutrient-dense meals designed to meet Health Canada DRI requirements:

- **13 breakfasts (B1-B13)**: Oatmeal with Banana, Scrambled Eggs with Toast, Cereal with Milk, Peanut Butter Toast, Yogurt with Banana, Pancakes with Butter, Loaded Breakfast Burrito, PB Banana Oatmeal, Egg Cheese Avocado Toast, Yogurt Granola with Berries and OJ, Oatmeal with Nuts and Orange, Eggs with Cheese Toast and OJ, Fortified Cereal with OJ and Egg
- **16 lunches (L1-L16)**: Grilled Cheese, Pasta with Tomato Sauce, Rice and Beans, Tuna Sandwich, Chicken Wrap, Ramen with Egg, Quesadilla with Salsa, Burrito Bowl, Peanut Noodles, Chickpea Rice Bowl, Loaded Grilled Cheese, Salmon Rice Bowl, Sardine Toast with Spinach, Chicken Pasta with Kale, Sardine Rice with Kale, Salmon Pasta with Spinach
- **19 dinners (D1-D19)**: Chicken Stir-Fry with Rice, Spaghetti Bolognese, Baked Potato, Bean Chili, Fried Rice with Egg, Chicken Nuggets with Veggies, Lentil Soup, Beef Pasta Bake, Chicken Fried Rice Deluxe, Triple Bean Chili, Loaded Baked Potato, PB Ramen, Salmon Stir-Fry with Rice, Sardine Pasta, Beef Chili with Beans, Cheesy Chicken Rice with Broccoli, Salmon Lentil Stew, Bean and Kale Rice Bowl, Sardine Lentil Stew

`meal_ingredients.csv` defines the recipe matrix **r[m,j]** — the amount of ingredient `j` (in grams or mL) required for one serving of meal `m`. Units are standardized to match the `package_unit` in `ingredient_prices.csv` so that the waste balance constraint works correctly.

### 1C · Nutritional Data (`compute_nutrition.py` -> `data/meal_nutrients.csv`)

Per-100g nutritional values for all 58 ingredients are embedded in `compute_nutrition.py` (sourced from USDA FoodData Central / Canadian Nutrient File). The script multiplies by recipe amounts and sums across ingredients to produce **14 nutrients per meal**:

calories, protein, fat, carbohydrates, fiber, sugar, sodium, calcium, iron, potassium, vitamin D, B12, folate, magnesium

To regenerate:
```bash
python compute_nutrition.py
```

---

## Phase 2 — MIP Model (`model.py`)

### Formulation

**Sets**
- `M = B ∪ L ∪ D` — 48 meals partitioned into Breakfast, Lunch, Dinner
- `I = {1, ..., 7}` — days of the week
- `N` — 14 tracked nutrients
- `J` — 58 ingredients

**Decision Variables**
- `x[m,i] in {0,1}` — 1 if meal `m` is selected on day `i`
- `y[j] in Z+` — number of packages of ingredient `j` to purchase
- `w[j] >= 0` — waste of ingredient `j` (in grams or mL)

**Objective**
```
min  sum_j  p_j * y_j  +  lambda * sum_j  (p_j / s_j) * w_j
```
- First term: total grocery cost
- Second term: cost-weighted waste (waste measured in dollars, not raw units)
- `lambda` (default 0.5) controls the cost-waste tradeoff

**Constraints**

| ID | Description |
|---|---|
| C1-C3 | Exactly one breakfast / lunch / dinner per day |
| C4 | Each breakfast meal used at most 3 times per week |
| C5 | Each lunch meal used at most 2 times per week |
| C6 | Each dinner meal used at most 2 times per week |
| C7 | No meal repeated on consecutive days |
| C8 | Daily nutrient lower and upper bounds (14 nutrients x 7 days) |
| C9 | Weekly calorie bounds (12,600-19,600 kcal) |
| C11 | Waste balance: `w[j] = y[j]*s[j] - sum_{m,i} r[m,j]*x[m,i]` |

---

### Nutritional Bounds and Feasibility

#### Lower Bounds: Health Canada DRIs (Strict)

All lower bounds are set to the **Health Canada / NASEM Dietary Reference Intakes** (RDA or AI) for adults aged 19-30. These are unchanged from the official recommendations:

| Nutrient | LB (Health Canada RDA/AI) | Source |
|---|---|---|
| Calories | 1800 kcal | EER for sedentary female 19-30 |
| Protein | 46 g | RDA (female 19-30) |
| Fat | 44 g | AMDR lower end (20% of 2000 kcal) |
| Carbohydrates | 225 g | AMDR lower end (45% of 2000 kcal) |
| Fiber | 25 g | AI (female 19-30) |
| Sodium | 500 mg | Minimum physiological need |
| Calcium | 1000 mg | RDA (adults 19-30) |
| Iron | 8 mg | RDA (male 19-30) |
| Potassium | 2600 mg | AI (female 19-30, NASEM 2019) |
| Vitamin D | 600 IU | RDA (adults 19-50, NASEM 2011) |
| B12 | 2.4 mcg | RDA (adults) |
| Folate | 400 mcg DFE | RDA (adults) |
| Magnesium | 310 mg | RDA (female 19-30) |

Sources: [Health Canada DRI Tables](https://www.canada.ca/en/health-canada/services/food-nutrition/healthy-eating/dietary-reference-intakes/tables.html), [NASEM DRI Reference Tables (NCBI)](https://www.ncbi.nlm.nih.gov/books/NBK208874/), [NIH Vitamin D Fact Sheet](https://ods.od.nih.gov/factsheets/VitaminD-HealthProfessional/), [NASEM Sodium & Potassium DRIs (2019)](https://www.nationalacademies.org/read/25353/chapter/11)

#### Upper Bounds: Safety-Based Relaxation

Some DRI upper bounds are **Tolerable Upper Intake Levels (ULs)** — actual toxicity thresholds. Others are AMDR-based guidelines or chronic disease recommendations with no established toxicological risk. We keep the former strict and moderately relax the latter:

**Relaxed upper bounds (no toxicity risk):**

| Nutrient | DRI UB | Model UB | Justification |
|---|---|---|---|
| **Fat** | 78 g (AMDR 35%) | **120 g** | AMDR is a chronic disease guideline, not a toxicity limit. No UL established. Many healthy diets (e.g. Mediterranean) exceed 35% calories from fat. |
| **Carbs** | 325 g (AMDR 65%) | **400 g** | AMDR upper end, not a toxicity limit. No UL established. |
| **Sugar** | 50 g (WHO 10%) | **75 g** | WHO recommendation for chronic disease prevention. No UL established. Exceeding 10% of calories from sugar is common and not acutely harmful. |
| **Sodium** | 2300 mg (CDRR) | **3000 mg** | The 2300 mg value is a Chronic Disease Risk Reduction intake (CDRR), not a UL. NASEM (2019) explicitly states no toxicological UL could be established. Average Canadian intake is ~3400 mg/day. |
| **Magnesium** | 420 mg | **600 mg** | The NASEM UL of 350 mg applies **only to supplemental (pharmacological) magnesium**, not dietary magnesium from food. "Extra magnesium from food is safe because the kidneys will eliminate excess amounts in urine" (NIH ODS). No adverse effects from food-sourced Mg. |
| **Calories** | 2500 kcal | **2800 kcal** | Varies by activity level. Not a safety limit. |

**Strict upper bounds (actual toxicity risk — unchanged):**

| Nutrient | UL | Risk if exceeded |
|---|---|---|
| **Iron** | 45 mg | GI distress, organ toxicity at sustained high doses |
| **Calcium** | 2500 mg | Kidney stones, hypercalcemia |
| **Vitamin D** | 4000 IU | Hypercalcemia from sustained high intake |
| **Folate** | 1000 mcg DFE | Can mask B12 deficiency (pernicious anemia) |
| **Potassium** | 4700 mg | Cardiac arrhythmia risk |
| **Protein** | 175 g | No UL, kept conservative |
| **B12** | 200 mcg | No UL, kept conservative |
| **Fiber** | 60 g | No UL, kept conservative |

Sources: [NIH Magnesium Fact Sheet](https://ods.od.nih.gov/factsheets/Magnesium-HealthProfessional/), [NASEM Sodium & Potassium DRIs (2019)](https://www.nationalacademies.org/news/sodium-and-potassium-dietary-reference-intake-values-updated-in-new-report), [NCBI AMDR Description](https://www.ncbi.nlm.nih.gov/books/NBK610333/)

#### How Feasibility Was Achieved

The initial 20-meal database was infeasible under strict DRI lower bounds due to five structural conflicts:

1. **Vitamin D gap**: The best possible day from the original 20 meals yielded only 378 IU (DRI requires 600 IU). No combination of meals from the original database could reach the vitamin D floor.
2. **Calcium + Calories conflict**: Calcium-rich meals (grilled cheese, quesadilla) were low-calorie; high-calorie meals (stir-fry, bolognese) were low-calcium.
3. **Fiber + Calcium conflict**: High-fiber meals (beans, lentils) were low-calcium; high-calcium meals (dairy) were low-fiber.
4. **Magnesium variety conflict**: Only a few meals had sufficient magnesium, making the 310 mg/day floor infeasible under the 3-use variety limit.
5. **Folate gap**: Most meals were low in folate, making the 400 mcg/day floor difficult to achieve jointly with other constraints.

An exhaustive enumeration of all 2688 possible (breakfast, lunch, dinner) triples from the original database confirmed that **zero combinations** satisfied all 14 strict DRI bounds simultaneously. The hardest constraints were:

| Constraint | % of triples failing |
|---|---|
| Vitamin D LB (600 IU) | 86.5% |
| Fiber LB (25 g) | 66.1% |
| Sodium UB (2300 mg) | 64.1% |
| Fat UB (78 g) | 61.9% |
| Folate LB (400 mcg) | 60.5% |

To resolve these conflicts, we:
1. Added **10 new nutrient-dense ingredients** (canned salmon, canned sardines, fortified OJ, kale, mixed nuts, kidney beans, oranges, strawberries, frozen berries, dark chocolate)
2. Designed **16 new meals** specifically targeting the nutrient gaps — salmon and sardine dishes for vitamin D, lentil-kale combos for folate + fiber, fortified OJ pairings for calcium + vitamin D
3. Relaxed 6 upper bounds that are AMDR/chronic-disease guidelines (not toxicity limits) — see table above

This combination produces a feasible model where **every daily lower bound matches the Health Canada DRI**.

#### The `--relax` Flag

The `--relax` flag further reduces all lower bounds to ~20-75% of DRI values. This is provided for comparison and sensitivity analysis — it shows how much cheaper a plan becomes when nutritional standards are loosened. It is **not the recommended mode**.

### Optimal Results (lambda=0.5, default bounds)

- **Grocery cost:** $117.41
- **Waste penalty:** $26.79 (raw waste value $53.57)
- **Total objective:** $144.20
- 27 distinct grocery items purchased
- All 7 days meet every Health Canada DRI lower bound
- Daily calorie range: 1881-2232 kcal
- Daily vitamin D range: 662-1498 IU (all above 600 IU floor)
- Daily calcium range: 1020-1834 mg (all above 1000 mg floor)

---

## Phase 3 — Analysis

### 3A · Sensitivity Analysis (`analysis.py`)

Three experiments, all plots saved to `results/plots/`:

**Experiment 1 — Lambda sweep (lambda = 0 -> 2)**
Grocery cost stays near $117 across all lambda values. Waste drops slightly at low lambda then plateaus. The model hits a structural floor: buying fewer packages than needed is infeasible, so waste reduction beyond a threshold cannot occur without changing the meal plan.

**Experiment 2 — Repetition limits (1-5 uses per lunch/dinner)**
Tests how variety constraints affect cost and feasibility.

**Experiment 3 — Caloric profiles**
Tests different calorie ranges for different activity/sex profiles.

### 3B · LP Relaxation & Shadow Prices (`lp_relaxation.py`)

Uses `Model.relax()` (the correct Gurobi API) to create a pure LP by dropping all integrality constraints.

**Key findings:**
- The integrality gap is very large, meaning the binary structure of meal selection (must pick exactly one complete meal per slot per day) accounts for most of the total cost.
- In the LP relaxation, **all daily nutrient bounds are non-binding** (shadow price = 0). The LP can trivially satisfy all 14 nutrient constraints by mixing fractional meals optimally.
- The **binding constraints** are the structural ones: meal slot assignments (C1-C3), variety limits (C5/C6), and waste balance (C11).

---

## Key Modeling Decisions

**Why no preference or difficulty scores?**
The meal database was pre-curated to include only meals students would realistically make and eat. Adding preference weights would introduce subjective parameters with no principled calibration. The feasibility of each meal is implicitly guaranteed by the curated list.

**Why cost-weighted waste (not raw grams)?**
Penalizing `sum w_j` directly mixes incompatible units (grams of rice vs. mL of oil vs. grams of cheese). The objective uses `(p_j / s_j) * w_j` — the unit price times waste amount — giving waste a consistent dollar value across all ingredients.

**Why LP relaxation for duals (not MIP duals)?**
Gurobi does not compute dual variables for MIP models (only LP duals are meaningful). The LP relaxation obtained via `Model.relax()` gives shadow prices that reflect the continuous cost structure.

**Why relax some upper bounds?**
The Health Canada DRI framework has two types of upper limits: (1) **ULs** — toxicity-based thresholds backed by clinical evidence (iron, calcium, vitamin D, folate), and (2) **AMDRs/CDRRs** — chronic disease risk guidelines with no established adverse effect level (fat, carbs, sodium, sugar, magnesium from food). Relaxing the second type is nutritionally defensible because exceeding them poses no acute or sub-acute health risk for healthy adults 19-30. Keeping strict lower bounds ensures the plan meets all minimum nutrient requirements.

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
lxml
undetected-chromedriver   # for Zehrs.ca scraping
```

Install with:
```bash
pip install -r requirements.txt
```
