"""
scrape_prices.py
----------------
Attempts to scrape grocery prices from Walmart.ca for the Waterloo, ON store
(postal code N2L).  If the site returns non-200 / blocks the request the
script falls back to the manually-curated CSV already present in
data/ingredient_prices.csv so the rest of the pipeline keeps working.

Also downloads and parses StatCan Table 18-10-0245-01 as a validation
source for common staples.

Usage:
    python scrape_prices.py [--validate-statcan]
"""

import argparse
import csv
import io
import os
import time
import zipfile
from datetime import date

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WALMART_SEARCH_URL = (
    "https://www.walmart.ca/api/product-page/search-by-keyword"
    "?query={query}&lang=en&current=1&pageSize=48&sortBy=1"
)

STATCAN_URL = (
    "https://www150.statcan.gc.ca/n1/tbl/csv/18100245-eng.zip"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.walmart.ca/en/grocery/",
}

# Postal code for Waterloo, ON (used for store-location cookie)
WATERLOO_POSTAL = "N2L3G1"

OUTPUT_CSV = os.path.join("data", "ingredient_prices.csv")
STATCAN_CSV = os.path.join("data", "statcan_prices.csv")

# Search terms mapped to the ingredient IDs we care about
SEARCH_TERMS = {
    "chicken_breast": "boneless skinless chicken breast",
    "ground_beef": "lean ground beef",
    "eggs": "large eggs dozen",
    "canned_tuna": "flaked light tuna",
    "tofu": "firm tofu",
    "canned_black_beans": "black beans canned",
    "lentils": "green lentils",
    "white_rice": "long grain white rice",
    "pasta_spaghetti": "spaghetti pasta",
    "bread_white": "white sandwich bread",
    "oats": "quick oats",
    "tortillas": "flour tortillas",
    "cereal": "corn flakes cereal",
    "ramen_noodles": "instant ramen noodles",
    "milk_2l": "2% milk 2L",
    "cheese_cheddar": "medium cheddar cheese block",
    "butter": "salted butter",
    "yogurt_plain": "plain yogurt",
    "bananas": "bananas",
    "apples": "gala apples",
    "tomatoes": "roma tomatoes",
    "onions": "yellow onions",
    "garlic": "garlic bulb",
    "potatoes": "russet potatoes",
    "carrots": "baby carrots",
    "broccoli": "broccoli",
    "spinach": "baby spinach",
    "lettuce": "iceberg lettuce",
    "bell_peppers": "bell peppers",
    "frozen_mixed_veg": "frozen mixed vegetables",
    "olive_oil": "extra virgin olive oil",
    "vegetable_oil": "vegetable oil",
    "peanut_butter": "smooth peanut butter",
    "flour": "all purpose flour",
    "sugar": "granulated white sugar",
    "salt": "table salt",
    "soy_sauce": "soy sauce",
    "tomato_sauce": "tomato pasta sauce",
    "canned_tomatoes": "diced tomatoes canned",
    "canned_corn": "whole kernel corn canned",
    "salsa": "medium salsa",
    "frozen_chicken_nuggets": "chicken nuggets frozen",
}


def try_walmart_scrape() -> dict:
    """
    Attempt to hit the Walmart.ca JSON search API.
    Returns a dict {ingredient_id: {price, name, ...}} or empty dict on failure.
    """
    session = requests.Session()
    # Set location cookie
    session.cookies.set("walmart_location", WATERLOO_POSTAL, domain="www.walmart.ca")

    results = {}
    for ing_id, query in SEARCH_TERMS.items():
        url = WALMART_SEARCH_URL.format(query=requests.utils.quote(query))
        try:
            resp = session.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                print(f"  [{ing_id}] HTTP {resp.status_code} — skipping")
                continue
            data = resp.json()
            items = data.get("items", [])
            if not items:
                print(f"  [{ing_id}] no results")
                continue
            item = items[0]
            price = (
                item.get("priceObject", {}).get("displayPrice")
                or item.get("salePrice")
                or item.get("price")
            )
            results[ing_id] = {
                "ingredient_name": item.get("name", query),
                "price_cad": price,
                "source_url": f"https://www.walmart.ca/en/search?q={query}",
            }
            print(f"  [{ing_id}] ${price}  — {item.get('name','')[:60]}")
        except Exception as exc:
            print(f"  [{ing_id}] error: {exc}")
        time.sleep(0.3)   # polite delay

    return results


def download_statcan() -> None:
    """
    Download StatCan Table 18-10-0245-01 and filter for Ontario,
    saving the most recent month to data/statcan_prices.csv.
    """
    print("\nDownloading StatCan Table 18-10-0245-01 …")
    try:
        resp = requests.get(STATCAN_URL, timeout=60)
        resp.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(resp.content))
        csv_name = [n for n in z.namelist() if n.endswith(".csv") and "18100245" in n]
        if not csv_name:
            csv_name = [n for n in z.namelist() if n.endswith(".csv")]
        if not csv_name:
            print("  Could not find CSV inside zip.")
            return
        raw = z.read(csv_name[0]).decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(raw))
        rows = [r for r in reader if "Ontario" in r.get("GEO", "")]
        if not rows:
            print("  No Ontario rows found.")
            return
        # Keep only the most recent REF_DATE
        max_date = max(r["REF_DATE"] for r in rows)
        rows = [r for r in rows if r["REF_DATE"] == max_date]
        os.makedirs("data", exist_ok=True)
        with open(STATCAN_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=reader.fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"  Saved {len(rows)} Ontario rows (period: {max_date}) → {STATCAN_CSV}")
    except Exception as exc:
        print(f"  StatCan download failed: {exc}")


def main():
    parser = argparse.ArgumentParser(description="Scrape Walmart.ca grocery prices")
    parser.add_argument(
        "--validate-statcan",
        action="store_true",
        help="Also download StatCan retail price table for validation",
    )
    args = parser.parse_args()

    print("=== Walmart.ca Price Scraper ===")
    print("Attempting live scrape …")
    scraped = try_walmart_scrape()

    if len(scraped) >= 10:
        print(f"\nScraped {len(scraped)} items successfully.")
        # Would merge with manual CSV here; for now just report
    else:
        print(
            f"\nOnly {len(scraped)} items scraped (anti-bot protection likely active)."
        )
        print(f"Falling back to manually curated data in {OUTPUT_CSV}")
        if os.path.exists(OUTPUT_CSV):
            print("  ✓ Fallback CSV already present — no action needed.")
        else:
            print("  ✗ Fallback CSV not found. Please populate data/ingredient_prices.csv manually.")

    if args.validate_statcan:
        download_statcan()

    print("\nDone.")


if __name__ == "__main__":
    main()
