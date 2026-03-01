from playwright.sync_api import sync_playwright

SEEDS = list(range(9, 19))
BASE_URL = "https://sanand0.github.io/tdsdata/js_table/?seed={}"

def main():
    grand_total = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for seed in SEEDS:
            url = BASE_URL.format(seed)
            print(f"Visiting {url}")
            page.goto(url)
            page.wait_for_selector("table")

            tables = page.query_selector_all("table")

            for table in tables:
                cells = table.query_selector_all("td")
                for cell in cells:
                    text = cell.inner_text().strip()
                    try:
                        number = float(text)
                        grand_total += number
                    except:
                        continue

        browser.close()

    print("FINAL TOTAL:", grand_total)

if __name__ == "__main__":
    main()