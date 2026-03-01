import requests
from bs4 import BeautifulSoup
import json
import re

url = "https://www.imdb.com/search/title/?user_rating=4.0,8.0&sort=moviemeter,asc&count=25"

headers = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9"
}

response = requests.get(url, headers=headers)
soup = BeautifulSoup(response.text, "html.parser")

movies = []

items = soup.select("li.ipc-metadata-list-summary-item")

for item in items[:25]:
    link = item.find("a", href=True)
    id_match = re.search(r"(tt\d+)", link["href"])
    movie_id = id_match.group(1) if id_match else ""

    title = item.find("h3").get_text(strip=True)

    year_tag = item.find("span", class_="sc-14dd939d-6")
    year = year_tag.get_text(strip=True) if year_tag else ""

    rating_tag = item.find("span", class_="ipc-rating-star--rating")
    rating = rating_tag.get_text(strip=True) if rating_tag else ""

    movies.append({
        "id": movie_id,
        "title": title,
        "year": year,
        "rating": rating
    })

print(json.dumps(movies, indent=2))