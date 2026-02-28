import asyncio
from playwright.async_api import async_playwright

START_URL = "https://sanand0.github.io/tdsdata/cdp_trap/index.html?student=23f2005747%40ds.study.iitm.ac.in"

visited_pages = set()
error_pages = set()
first_error_page = None


async def run():
    global first_error_page

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        async def handle_page_error(exception):
            nonlocal page
            global first_error_page

            page_name = page.url.split("/")[-1]
            error_pages.add(page_name)

            if first_error_page is None:
                first_error_page = page_name

        page.on("pageerror", handle_page_error)

        await page.goto(START_URL)

        # BFS style navigation through 15 pages
        to_visit = [page.url]

        while to_visit:
            current = to_visit.pop(0)

            if current in visited_pages:
                continue

            visited_pages.add(current)
            await page.goto(current)

            # wait for async errors (1-3 sec)
            await page.wait_for_timeout(3000)

            # collect all links
            links = await page.eval_on_selector_all(
                "a",
                "elements => elements.map(e => e.href)"
            )

            for link in links:
                if link not in visited_pages and link not in to_visit:
                    to_visit.append(link)

        await browser.close()


asyncio.run(run())

print(f"TOTAL_PAGES_VISITED={len(visited_pages)}")
print(f"TOTAL_ERRORS={len(error_pages)}")
print(f"FIRST_ERROR_PAGE={first_error_page}")