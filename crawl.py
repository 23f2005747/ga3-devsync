import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

BASE = "https://sanand0.github.io/tdsdata/crawl_html/"

visited = set()
all_html_pages = set()

def crawl(url):
    if url in visited:
        return
    visited.add(url)

    try:
        r = requests.get(url)
    except:
        return

    if r.status_code != 200:
        return

    soup = BeautifulSoup(r.text, "html.parser")

    # If it's an HTML page inside base path
    if url.startswith(BASE) and url.endswith(".html"):
        all_html_pages.add(url)

    for a in soup.find_all("a", href=True):
        next_url = urljoin(url, a['href'])

        # stay inside domain
        if next_url.startswith(BASE):
            crawl(next_url)

crawl(BASE)

count = 0

for url in all_html_pages:
    filename = url.split("/")[-1]
    if filename:
        first_letter = filename[0].upper()
        if "M" <= first_letter <= "Z":
            count += 1

print("TOTAL FILES:", count)