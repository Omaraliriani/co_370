"""
Scrapes grocery prices from Walmart.ca and Zehrs.ca for Waterloo/Kitchener.

For each ingredient:
  1. Queries Walmart.ca search (HTML + __NEXT_DATA__ JSON)
  2. Scrapes Zehrs.ca with Selenium (headless Chrome)
  3. Averages both prices; falls back to existing CSV if scraping fails
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

STATCAN_URL = "https://www150.statcan.gc.ca/n1/tbl/csv/18100245-eng.zip"
OUTPUT_CSV = os.path.join("data", "ingredient_prices.csv")
STATCAN_CSV = os.path.join("data", "statcan_prices.csv")

# Ingredient search terms for each store
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


def parse_package_size(text):
    """Extract package size and unit from product title."""
    text = text.lower()
    m = re.search(r'(\d+(?:\.\d+)?)\s*kg', text)
    if m:
        return int(float(m.group(1)) * 1000), "g"
    m = re.search(r'(\d+(?:\.\d+)?)\s*ml', text)
    if m:
        return int(float(m.group(1))), "mL"
    m = re.search(r'(\d+(?:\.\d+)?)\s*l\b', text)
    if m:
        return int(float(m.group(1)) * 1000), "mL"
    m = re.search(r'(?<!k)(\d+(?:\.\d+)?)\s*g\b', text)
    if m:
        return int(float(m.group(1))), "g"
    return None, None


def parse_price(text):
    """Extract a numeric price from text like '$4.97'."""
    for m in re.findall(r'\$\s*(\d+\.\d{2})', text):
        val = float(m)
        if val > 0:
            return val
    return None


def get_chrome_version():
    """Detect installed Chrome major version (Windows)."""
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


# --- Walmart scraper (requests-based) ---

WALMART_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/146.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}


def scrape_walmart(search_terms):
    """Scrape Walmart.ca via search page HTML + __NEXT_DATA__ JSON."""
    import json
    session = requests.Session()
    session.headers.update(WALMART_HEADERS)
    results = {}

    for ing_id, query in search_terms.items():
        url = f"https://www.walmart.ca/search?q={requests.utils.quote(query)}&c=10019"
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                time.sleep(random.uniform(1, 3))
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            price, name, pkg_size, pkg_unit = None, query, None, None

            # Try __NEXT_DATA__ JSON first
            next_data = soup.select_one("script#__NEXT_DATA__")
            if next_data:
                try:
                    data = json.loads(next_data.string)
                    props = data.get("props", {}).get("pageProps", {})
                    items = None
                    if "searchResult" in props:
                        items = props["searchResult"].get("itemStacks", [{}])
                        if items: items = items[0].get("items", [])
                    elif "initialData" in props:
                        sd = props["initialData"].get("searchResult", {})
                        items = sd.get("itemStacks", [{}])
                        if items: items = items[0].get("items", [])
                    if items:
                        for item in items[:3]:
                            p = item.get("priceInfo", {})
                            current = p.get("currentPrice", {}).get("price")
                            if current and current > 0:
                                price = current
                                name = item.get("name", query)[:80]
                                pkg_size, pkg_unit = parse_package_size(name)
                                break
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass

            # Fallback: parse HTML tiles
            if price is None:
                tiles = soup.select("div[data-item-id]")
                if tiles:
                    tile = tiles[0]
                    price_el = tile.select_one("[data-automation-id='product-price']")
                    if price_el:
                        price = parse_price(price_el.get_text(" ", strip=True))
                    name_link = tile.select_one("a[href*='/ip/']")
                    if name_link:
                        name = name_link.get_text(strip=True)[:80]
                    if price is None:
                        for el in tile.select("div.b.black"):
                            price = parse_price(el.get_text())
                            if price: break
                    pkg_size, pkg_unit = parse_package_size(name)

            if price and price > 0:
                results[ing_id] = {
                    "price": price, "package_size": pkg_size,
                    "package_unit": pkg_unit, "name": name, "url": url,
                }
        except Exception:
            pass
        time.sleep(random.uniform(1, 3))

    return results


# --- Zehrs scraper (Selenium) ---

def _create_zehrs_driver(chrome_ver):
    opts = uc.ChromeOptions()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    return uc.Chrome(options=opts, version_main=chrome_ver)


def scrape_zehrs(chrome_ver, search_terms):
    """Scrape Zehrs.ca with headless Selenium."""
    driver = _create_zehrs_driver(chrome_ver)
    requests_since_restart = 0
    results = {}

    for ing_id, query in search_terms.items():
        url = f"https://www.zehrs.ca/search?search-bar={requests.utils.quote(query)}"
        try:
            if requests_since_restart >= 10:
                try: driver.quit()
                except Exception: pass
                time.sleep(2)
                driver = _create_zehrs_driver(chrome_ver)
                requests_since_restart = 0

            driver.get(url)
            requests_since_restart += 1
            time.sleep(random.uniform(5, 7))
            soup = BeautifulSoup(driver.page_source, "lxml")

            tiles = soup.select("div.chakra-linkbox") or soup.select("div.css-qoklea")
            if not tiles:
                continue

            # Skip sponsored tiles
            tile = None
            for t in tiles:
                link = t.select_one("a[href*='/p/']")
                if not link: continue
                if "source=sptd" in link.get("href", ""): continue
                tile = t
                break
            if tile is None:
                continue

            # Extract price
            price = None
            for cls in ["css-o93gbd", "css-s9i4ca", "css-pwnbcb"]:
                el = tile.select_one(f"span.{cls}")
                if el:
                    price = parse_price(el.get_text())
                    if price: break
            if price is None:
                for span in tile.find_all("span"):
                    txt = span.get_text(strip=True)
                    if "$" in txt and len(txt) < 15:
                        price = parse_price(txt)
                        if price: break

            # Extract name and package size
            name = query
            link = tile.select_one("a[href*='/p/']") or tile.select_one("a")
            if link: name = link.get_text(" ", strip=True)
            pkg_size, pkg_unit = None, None
            size_el = tile.select_one("p.css-1yftjin")
            if size_el: pkg_size, pkg_unit = parse_package_size(size_el.get_text())
            if pkg_size is None: pkg_size, pkg_unit = parse_package_size(name)
            if pkg_size is None: pkg_size, pkg_unit = parse_package_size(tile.get_text(" ", strip=True))

            if price and price > 0:
                results[ing_id] = {
                    "price": price, "package_size": pkg_size,
                    "package_unit": pkg_unit, "name": name[:80], "url": url,
                }
        except Exception as exc:
            if "invalid session" in str(exc).lower() or "session deleted" in str(exc).lower():
                try: driver.quit()
                except Exception: pass
                time.sleep(3)
                try:
                    driver = _create_zehrs_driver(chrome_ver)
                    requests_since_restart = 0
                except Exception:
                    break
        time.sleep(random.uniform(2, 4))

    try: driver.quit()
    except Exception: pass
    return results


# --- Merge + output ---

def load_fallback_csv():
    fallback = {}
    if not os.path.exists(OUTPUT_CSV):
        return fallback
    with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            fallback[row["ingredient_id"]] = row
    return fallback


def merge_and_average(walmart, zehrs, fallback):
    """Average prices from both stores; fall back to CSV for missing items."""
    rows = []
    today = date.today().isoformat()

    for ing_id in SEARCH_TERMS:
        w, z, fb = walmart.get(ing_id), zehrs.get(ing_id), fallback.get(ing_id)

        if w and z:
            avg_price = round((w["price"] + z["price"]) / 2, 2)
            pkg_size = w["package_size"] or z["package_size"]
            pkg_unit = w["package_unit"] or z["package_unit"]
            name, source = w["name"], f"{w['url']} | {z['url']}"
        elif w:
            avg_price, pkg_size, pkg_unit = w["price"], w["package_size"], w["package_unit"]
            name, source = w["name"], w["url"]
        elif z:
            avg_price, pkg_size, pkg_unit = z["price"], z["package_size"], z["package_unit"]
            name, source = z["name"], z["url"]
        elif fb:
            rows.append(fb)
            continue
        else:
            continue

        if pkg_size is None and fb:
            pkg_size = fb.get("package_size", "")
            pkg_unit = fb.get("package_unit", "")

        rows.append({
            "ingredient_id": ing_id, "ingredient_name": name,
            "price_cad": avg_price, "package_size": pkg_size if pkg_size else "",
            "package_unit": pkg_unit if pkg_unit else "",
            "category": CATEGORIES.get(ing_id, "pantry"),
            "source_url": source, "date_collected": today,
        })
    return rows


def write_csv(rows):
    os.makedirs("data", exist_ok=True)
    fields = ["ingredient_id", "ingredient_name", "price_cad", "package_size",
              "package_unit", "category", "source_url", "date_collected"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} ingredients to {OUTPUT_CSV}")


def download_statcan():
    """Download StatCan Table 18-10-0245-01 for Ontario price validation."""
    print("Downloading StatCan price data...")
    try:
        resp = requests.get(STATCAN_URL, timeout=60)
        resp.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(resp.content))
        csv_name = [n for n in z.namelist() if n.endswith(".csv") and "18100245" in n]
        if not csv_name:
            csv_name = [n for n in z.namelist() if n.endswith(".csv")]
        if not csv_name:
            return
        raw = z.read(csv_name[0]).decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(raw))
        rows = [r for r in reader if "Ontario" in r.get("GEO", "")]
        if not rows:
            return
        max_date = max(r["REF_DATE"] for r in rows)
        rows = [r for r in rows if r["REF_DATE"] == max_date]
        os.makedirs("data", exist_ok=True)
        with open(STATCAN_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=reader.fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"Saved {len(rows)} Ontario rows ({max_date}) -> {STATCAN_CSV}")
    except Exception as exc:
        print(f"StatCan download failed: {exc}")


def main():
    parser = argparse.ArgumentParser(description="Scrape grocery prices")
    parser.add_argument("--validate-statcan", action="store_true",
                        help="Download StatCan price table for validation")
    args = parser.parse_args()

    if not HAS_UC:
        print("ERROR: pip install undetected-chromedriver")
        return

    fallback = load_fallback_csv()
    chrome_ver = get_chrome_version()

    print(f"Scraping {len(SEARCH_TERMS)} ingredients (Chrome v{chrome_ver or '?'})...")

    walmart_results, zehrs_results = {}, {}
    try:
        walmart_results = scrape_walmart(SEARCH_TERMS)
        print(f"Walmart: {len(walmart_results)}/{len(SEARCH_TERMS)}")
    except Exception as e:
        print(f"Walmart failed: {e}")

    try:
        zehrs_results = scrape_zehrs(chrome_ver, SEARCH_TERMS)
        print(f"Zehrs: {len(zehrs_results)}/{len(SEARCH_TERMS)}")
    except Exception as e:
        print(f"Zehrs failed: {e}")

    total = len(set(walmart_results) | set(zehrs_results))
    threshold = len(SEARCH_TERMS) // 4

    if total >= threshold:
        merged = merge_and_average(walmart_results, zehrs_results, fallback)
        write_csv(merged)
    else:
        print(f"Only {total}/{len(SEARCH_TERMS)} scraped — keeping fallback CSV.")

    if args.validate_statcan:
        download_statcan()


if __name__ == "__main__":
    main()
