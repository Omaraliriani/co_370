"""
scrape_prices.py
----------------
Scrapes grocery prices from Walmart.ca (via API) and Zehrs.ca (via Selenium)
for the Waterloo / Kitchener area.

For each ingredient the scraper:
  1. Queries Walmart.ca's search API for price + package size
  2. Scrapes Zehrs.ca HTML with Selenium for price + package size
  3. Averages the prices from both stores

If scraping fails or returns too few items, the script falls back to the
manually-curated CSV in data/ingredient_prices.csv.

Requirements:
    pip install undetected-chromedriver beautifulsoup4 lxml requests

Usage:
    python scrape_prices.py [--validate-statcan]
"""

import argparse
import csv
import io
import os
import random
import re
import time
import zipfile
from datetime import date

import requests
from bs4 import BeautifulSoup

try:
    import undetected_chromedriver as uc
    HAS_UC = True
except ImportError:
    HAS_UC = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STATCAN_URL = (
    "https://www150.statcan.gc.ca/n1/tbl/csv/18100245-eng.zip"
)

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
    "cream_cheese": "cream cheese",
    "bacon": "bacon",
    "avocado": "avocado",
    "canned_chickpeas": "chickpeas canned",
    "honey": "liquid honey",
    "shredded_mozzarella": "shredded mozzarella cheese",
    "canned_salmon": "canned pink salmon",
    "canned_sardines": "canned sardines",
    "fortified_oj": "tropicana calcium vitamin D orange juice",
    "mixed_nuts": "mixed nuts",
    "orange": "oranges",
    "strawberries": "strawberries",
    "frozen_berries": "frozen mixed berries",
    "dark_chocolate": "dark chocolate bar",
    "kale": "kale",
    "canned_kidney_beans": "red kidney beans canned",
}

# Category mapping for each ingredient
CATEGORIES = {
    "chicken_breast": "proteins", "ground_beef": "proteins",
    "eggs": "dairy", "canned_tuna": "proteins", "tofu": "proteins",
    "canned_black_beans": "pantry", "lentils": "proteins",
    "white_rice": "grains", "pasta_spaghetti": "grains",
    "bread_white": "grains", "oats": "grains", "tortillas": "grains",
    "cereal": "grains", "ramen_noodles": "grains",
    "milk_2l": "dairy", "cheese_cheddar": "dairy", "butter": "dairy",
    "yogurt_plain": "dairy",
    "bananas": "produce", "apples": "produce", "tomatoes": "produce",
    "onions": "produce", "garlic": "produce", "potatoes": "produce",
    "carrots": "produce", "broccoli": "produce", "spinach": "produce",
    "lettuce": "produce", "bell_peppers": "produce",
    "frozen_mixed_veg": "produce",
    "olive_oil": "pantry", "vegetable_oil": "pantry",
    "peanut_butter": "pantry", "flour": "pantry", "sugar": "pantry",
    "salt": "pantry", "soy_sauce": "pantry", "tomato_sauce": "pantry",
    "canned_tomatoes": "pantry", "canned_corn": "pantry",
    "salsa": "pantry", "frozen_chicken_nuggets": "proteins",
    "cream_cheese": "dairy", "bacon": "proteins", "avocado": "produce",
    "canned_chickpeas": "pantry", "honey": "pantry",
    "shredded_mozzarella": "dairy",
    "canned_salmon": "proteins", "canned_sardines": "proteins",
    "fortified_oj": "produce", "mixed_nuts": "pantry",
    "orange": "produce", "strawberries": "produce",
    "frozen_berries": "produce", "dark_chocolate": "pantry",
    "kale": "produce", "canned_kidney_beans": "pantry",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_package_size(text):
    """
    Extract package size and unit from product title text.
    Returns (size_in_base_unit, unit) where unit is 'g' or 'mL',
    or (None, None) if no match.
    """
    text = text.lower()

    # kg -> g
    m = re.search(r'(\d+(?:\.\d+)?)\s*kg', text)
    if m:
        return int(float(m.group(1)) * 1000), "g"

    # mL / ml  (check before L to avoid false match)
    m = re.search(r'(\d+(?:\.\d+)?)\s*ml', text)
    if m:
        return int(float(m.group(1))), "mL"

    # L -> mL  (but not mL which was already caught)
    m = re.search(r'(\d+(?:\.\d+)?)\s*l\b', text)
    if m:
        return int(float(m.group(1)) * 1000), "mL"

    # g (but not kg)
    m = re.search(r'(?<!k)(\d+(?:\.\d+)?)\s*g\b', text)
    if m:
        return int(float(m.group(1))), "g"

    return None, None


def parse_price(text):
    """Extract a numeric price from text like '$4.97' or 'Now $6.47'."""
    # Find all prices in the text, return the first one > 0
    matches = re.findall(r'\$\s*(\d+\.\d{2})', text)
    for m in matches:
        val = float(m)
        if val > 0:
            return val
    return None


def get_chrome_version():
    """Detect the installed Chrome major version."""
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome_path):
        return None
    try:
        import subprocess
        result = subprocess.run(
            ['reg', 'query',
             r'HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon',
             '/v', 'version'],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            m = re.search(r'(\d+)\.\d+\.\d+\.\d+', result.stdout)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Walmart scraper (requests-based API)
# ---------------------------------------------------------------------------

WALMART_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}


def scrape_walmart(search_terms):
    """
    Scrape Walmart.ca by fetching the search page HTML and extracting
    the embedded __NEXT_DATA__ JSON (contains product info + prices).
    Falls back to parsing raw HTML if __NEXT_DATA__ is unavailable.
    """
    import json

    session = requests.Session()
    session.headers.update(WALMART_HEADERS)

    results = {}
    for ing_id, query in search_terms.items():
        url = f"https://www.walmart.ca/search?q={requests.utils.quote(query)}&c=10019"
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                print(f"  [walmart][{ing_id}] HTTP {resp.status_code}")
                time.sleep(random.uniform(1, 3))
                continue

            soup = BeautifulSoup(resp.text, "lxml")

            # Try to extract __NEXT_DATA__ JSON (Next.js SSR data)
            price = None
            name = query
            pkg_size, pkg_unit = None, None

            next_data = soup.select_one("script#__NEXT_DATA__")
            if next_data:
                try:
                    data = json.loads(next_data.string)
                    # Navigate the Next.js data structure to find products
                    props = data.get("props", {}).get("pageProps", {})
                    # Try different known paths for search results
                    items = None
                    if "searchResult" in props:
                        items = props["searchResult"].get("itemStacks", [{}])
                        if items:
                            items = items[0].get("items", [])
                    elif "initialData" in props:
                        sd = props["initialData"].get("searchResult", {})
                        items = sd.get("itemStacks", [{}])
                        if items:
                            items = items[0].get("items", [])

                    if items:
                        for item in items[:3]:  # check first 3 results
                            p = item.get("priceInfo", {})
                            current = p.get("currentPrice", {}).get("price")
                            if current and current > 0:
                                price = current
                                name = item.get("name", query)[:80]
                                pkg_size, pkg_unit = parse_package_size(name)
                                break
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass

            # Fallback: parse HTML product tiles
            if price is None:
                tiles = soup.select("div[data-item-id]")
                if tiles:
                    tile = tiles[0]
                    price_el = tile.select_one(
                        "[data-automation-id='product-price']"
                    )
                    if price_el:
                        price = parse_price(price_el.get_text(" ", strip=True))
                    name_link = tile.select_one("a[href*='/ip/']")
                    if name_link:
                        name = name_link.get_text(strip=True)[:80]
                    if price is None:
                        for el in tile.select("div.b.black"):
                            price = parse_price(el.get_text())
                            if price:
                                break
                    pkg_size, pkg_unit = parse_package_size(name)

            if price is not None and price > 0:
                results[ing_id] = {
                    "price": price,
                    "package_size": pkg_size,
                    "package_unit": pkg_unit,
                    "name": name,
                    "url": url,
                }
                size_str = f"{pkg_size}{pkg_unit}" if pkg_size else "?"
                print(f"  [walmart][{ing_id}] ${price:.2f} ({size_str}) — {name[:50]}")
            else:
                print(f"  [walmart][{ing_id}] could not parse price")

        except Exception as exc:
            err_msg = str(exc).split('\n')[0][:80]
            print(f"  [walmart][{ing_id}] error: {type(exc).__name__}: {err_msg}")

        time.sleep(random.uniform(1, 3))

    return results


# ---------------------------------------------------------------------------
# Zehrs scraper
# ---------------------------------------------------------------------------

def _create_zehrs_driver(chrome_ver):
    """Create a headless Chrome driver for Zehrs."""
    opts = uc.ChromeOptions()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    return uc.Chrome(options=opts, version_main=chrome_ver)


def scrape_zehrs(chrome_ver, search_terms):
    """
    Scrape Zehrs.ca search results.

    Zehrs DOM structure (as of 2026-04, Chakra UI):
      Product card: div.chakra-linkbox  or  div.css-qoklea
      Price:        span with css classes css-o93gbd, css-s9i4ca, css-pwnbcb
      Name/size:    a link text inside the card (brand + name + size)
      Size subtitle: p with class css-1yftjin  (e.g. "1.4 kg, $0.50/100g")

    Automatically recreates the browser if the session dies.
    """
    driver = _create_zehrs_driver(chrome_ver)
    requests_since_restart = 0

    results = {}
    for ing_id, query in search_terms.items():
        url = f"https://www.zehrs.ca/search?search-bar={requests.utils.quote(query)}"
        try:
            # Proactively restart browser every 10 requests to avoid session death
            if requests_since_restart >= 10:
                try:
                    driver.quit()
                except Exception:
                    pass
                time.sleep(2)
                driver = _create_zehrs_driver(chrome_ver)
                requests_since_restart = 0

            driver.get(url)
            requests_since_restart += 1
            time.sleep(random.uniform(5, 7))

            soup = BeautifulSoup(driver.page_source, "lxml")

            # Find product cards — Zehrs uses Chakra UI link boxes
            # or divs with specific css hash classes
            tiles = soup.select("div.chakra-linkbox")
            if not tiles:
                tiles = soup.select("div.css-qoklea")
            if not tiles:
                print(f"  [zehrs][{ing_id}] no product tiles found")
                time.sleep(random.uniform(1, 2))
                continue

            # Skip sponsored tiles (source=sptd) and tiles without product links
            tile = None
            for t in tiles:
                link = t.select_one("a[href*='/p/']")
                if not link:
                    continue  # skip banner/promo tiles with no product link
                href = link.get("href", "")
                if "source=sptd" in href:
                    continue  # skip sponsored products
                tile = t
                break

            if tile is None:
                print(f"  [zehrs][{ing_id}] no non-sponsored product tiles found")
                time.sleep(random.uniform(1, 2))
                continue

            # Extract price from spans with known CSS classes
            price = None
            for css_cls in ["css-o93gbd", "css-s9i4ca", "css-pwnbcb"]:
                price_el = tile.select_one(f"span.{css_cls}")
                if price_el:
                    price = parse_price(price_el.get_text())
                    if price and price > 0:
                        break
                    price = None

            # Fallback: find any span containing $ inside the tile
            if price is None:
                for span in tile.find_all("span"):
                    txt = span.get_text(strip=True)
                    if "$" in txt and len(txt) < 15:
                        p = parse_price(txt)
                        if p and p > 0:
                            price = p
                            break

            # Extract product name from link
            name = query
            link = tile.select_one("a[href*='/p/']")
            if not link:
                link = tile.select_one("a")
            if link:
                name = link.get_text(" ", strip=True)

            # Extract package size — first try the size subtitle
            pkg_size, pkg_unit = None, None
            size_el = tile.select_one("p.css-1yftjin")
            if size_el:
                pkg_size, pkg_unit = parse_package_size(size_el.get_text())
            if pkg_size is None:
                pkg_size, pkg_unit = parse_package_size(name)
            if pkg_size is None:
                pkg_size, pkg_unit = parse_package_size(
                    tile.get_text(" ", strip=True)
                )

            if price is not None and price > 0:
                results[ing_id] = {
                    "price": price,
                    "package_size": pkg_size,
                    "package_unit": pkg_unit,
                    "name": name[:80],
                    "url": url,
                }
                size_str = f"{pkg_size}{pkg_unit}" if pkg_size else "?"
                print(f"  [zehrs][{ing_id}] ${price:.2f} ({size_str}) — {name[:50]}")
            else:
                print(f"  [zehrs][{ing_id}] could not parse price")

        except Exception as exc:
            err_msg = str(exc).split('\n')[0][:80]
            print(f"  [zehrs][{ing_id}] error: {type(exc).__name__}: {err_msg}")
            # If session died, restart the browser
            if "invalid session" in str(exc).lower() or "session deleted" in str(exc).lower():
                print("  [zehrs] Browser session died — restarting...")
                try:
                    driver.quit()
                except Exception:
                    pass
                time.sleep(3)
                try:
                    driver = _create_zehrs_driver(chrome_ver)
                    requests_since_restart = 0
                except Exception as restart_exc:
                    print(f"  [zehrs] Could not restart browser: {restart_exc}")
                    break

        time.sleep(random.uniform(2, 4))

    try:
        driver.quit()
    except Exception:
        pass
    return results


# ---------------------------------------------------------------------------
# Merge and output
# ---------------------------------------------------------------------------

def load_fallback_csv():
    """Load existing ingredient_prices.csv as a dict keyed by ingredient_id."""
    fallback = {}
    if not os.path.exists(OUTPUT_CSV):
        return fallback
    with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fallback[row["ingredient_id"]] = row
    return fallback


def merge_and_average(walmart, zehrs, fallback):
    """
    Merge results from both stores. For each ingredient:
      - If both stores scraped: average the prices
      - If one store scraped: use that price
      - If neither: fall back to existing CSV data
    """
    rows = []
    today = date.today().isoformat()

    for ing_id in SEARCH_TERMS:
        w = walmart.get(ing_id)
        z = zehrs.get(ing_id)
        fb = fallback.get(ing_id)

        if w and z:
            avg_price = round((w["price"] + z["price"]) / 2, 2)
            pkg_size = w["package_size"] or z["package_size"]
            pkg_unit = w["package_unit"] or z["package_unit"]
            name = w["name"]
            source = f"{w['url']} | {z['url']}"
        elif w:
            avg_price = w["price"]
            pkg_size = w["package_size"]
            pkg_unit = w["package_unit"]
            name = w["name"]
            source = w["url"]
        elif z:
            avg_price = z["price"]
            pkg_size = z["package_size"]
            pkg_unit = z["package_unit"]
            name = z["name"]
            source = z["url"]
        elif fb:
            rows.append(fb)
            continue
        else:
            print(f"  WARNING: no data for {ing_id} from any source")
            continue

        # If we couldn't parse package size, use fallback values
        if pkg_size is None and fb:
            pkg_size = fb.get("package_size", "")
            pkg_unit = fb.get("package_unit", "")

        rows.append({
            "ingredient_id": ing_id,
            "ingredient_name": name,
            "price_cad": avg_price,
            "package_size": pkg_size if pkg_size else "",
            "package_unit": pkg_unit if pkg_unit else "",
            "category": CATEGORIES.get(ing_id, "pantry"),
            "source_url": source,
            "date_collected": today,
        })

    return rows


def write_csv(rows):
    """Write merged results to ingredient_prices.csv."""
    os.makedirs("data", exist_ok=True)
    fieldnames = [
        "ingredient_id", "ingredient_name", "price_cad", "package_size",
        "package_unit", "category", "source_url", "date_collected",
    ]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {len(rows)} ingredients to {OUTPUT_CSV}")


# ---------------------------------------------------------------------------
# StatCan validation (unchanged)
# ---------------------------------------------------------------------------

def download_statcan():
    """
    Download StatCan Table 18-10-0245-01 and filter for Ontario,
    saving the most recent month to data/statcan_prices.csv.
    """
    print("\nDownloading StatCan Table 18-10-0245-01 ...")
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
        max_date = max(r["REF_DATE"] for r in rows)
        rows = [r for r in rows if r["REF_DATE"] == max_date]
        os.makedirs("data", exist_ok=True)
        with open(STATCAN_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=reader.fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"  Saved {len(rows)} Ontario rows (period: {max_date}) -> {STATCAN_CSV}")
    except Exception as exc:
        print(f"  StatCan download failed: {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scrape Walmart.ca & Zehrs.ca grocery prices (Waterloo/Kitchener)"
    )
    parser.add_argument(
        "--validate-statcan",
        action="store_true",
        help="Also download StatCan retail price table for validation",
    )
    args = parser.parse_args()

    print("=== Dual-Store Price Scraper (Walmart.ca + Zehrs.ca) ===")
    print(f"Scraping prices for {len(SEARCH_TERMS)} ingredients...\n")

    if not HAS_UC:
        print("ERROR: undetected-chromedriver is required.")
        print("Install with: pip install undetected-chromedriver")
        return

    # Load existing CSV as fallback
    fallback = load_fallback_csv()
    print(f"Loaded {len(fallback)} items from fallback CSV\n")

    # Detect Chrome version
    chrome_ver = get_chrome_version()
    print(f"Detected Chrome version: {chrome_ver or 'unknown'}\n")

    walmart_results = {}
    zehrs_results = {}

    # --- Walmart (requests-based API, no browser needed) ---
    try:
        print("--- Scraping Walmart.ca (API) ---")
        walmart_results = scrape_walmart(SEARCH_TERMS)
        print(f"\nWalmart: scraped {len(walmart_results)}/{len(SEARCH_TERMS)} items")
    except Exception as exc:
        print(f"\nWalmart scraping failed: {exc}")

    # --- Zehrs (headless with auto-restart) ---
    try:
        print("\n--- Scraping Zehrs.ca (headless Selenium) ---")
        zehrs_results = scrape_zehrs(chrome_ver, SEARCH_TERMS)
        print(f"\nZehrs: scraped {len(zehrs_results)}/{len(SEARCH_TERMS)} items")
    except Exception as exc:
        print(f"\nZehrs scraping failed: {exc}")

    # --- Merge results ---
    total_scraped = len(set(walmart_results) | set(zehrs_results))
    threshold = len(SEARCH_TERMS) // 4  # 25% threshold

    if total_scraped >= threshold:
        print(f"\nScraped {total_scraped}/{len(SEARCH_TERMS)} items from at least one store.")
        merged = merge_and_average(walmart_results, zehrs_results, fallback)
        write_csv(merged)
    else:
        print(f"\nOnly {total_scraped}/{len(SEARCH_TERMS)} items scraped (threshold: {threshold}).")
        if fallback:
            print(f"Keeping existing fallback CSV ({len(fallback)} items) -- no changes made.")
        else:
            print("WARNING: No fallback CSV found.")

    if args.validate_statcan:
        download_statcan()

    print("\nDone.")


if __name__ == "__main__":
    main()
