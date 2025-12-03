import asyncio
import aiohttp
import requests
from bs4 import BeautifulSoup

URL = "https://steamunderground.net/wp-admin/admin-ajax.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://steamunderground.net/",
    "X-Requested-With": "XMLHttpRequest",
}


def search_game_sync(query):
    """
    BLOCKING function using 'requests' to perform the search.
    """
    payload = {"action": "bk_ajax_search", "s": query}
    try:
        response = requests.post(URL, data=payload, headers=HEADERS)
        response.raise_for_status()

        try:
            raw_json = response.json()
        except Exception:
            return []

        html_content = raw_json.get("content", "")
        soup = BeautifulSoup(html_content, "html.parser")

        results = []
        items = soup.find_all("li", class_="small-post")

        for item in items:
            title_tag = item.find("h4", class_="title").find("a")
            if title_tag and title_tag.get("href"):
                results.append(
                    {
                        "title": title_tag.text.strip(),
                        "url": title_tag["href"],
                        "source": "SteamUnderground",
                    }
                )
        return results

    except Exception as e:
        print(f"[SteamUnderground] Search error: {e}")
        return []


async def get_game_details(session, basic_data):
    """
    ASYNC function. Fetches details and handles lazy-loaded images.
    """
    url = basic_data["url"]
    try:
        async with session.get(url, headers=HEADERS) as response:
            response.raise_for_status()
            html_content = await response.text()

        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Cover Image (Improved Logic)
        # WordPress often hides the real image in 'data-src' or 'data-lazy-src'
        img_tag = soup.select_one(".s-feat-img img")
        image = None
        if img_tag:
            image = (
                img_tag.get("data-src")
                or img_tag.get("data-lazy-src")
                or img_tag.get("src")
            )

        # 2. Metadata
        version_tag = soup.select_one(".gameVersionValue")
        group_tag = soup.select_one(".releaseGroupValue")
        metadata = {
            "version": version_tag.text.strip() if version_tag else "N/A",
            "release_group": group_tag.text.strip() if group_tag else "N/A",
        }

        # 3. Sys Reqs
        sys_reqs = []
        req_header = soup.find(
            lambda tag: tag.name == "h3" and "System requirements" in tag.text
        )
        if req_header:
            req_list = req_header.find_next("ul")
            if req_list:
                sys_reqs = [
                    li.get_text(" ", strip=True) for li in req_list.find_all("li")
                ][:5]

        # 4. Downloads
        download_links = []
        for btn in soup.select(".DownloadButtonContainer a"):
            download_links.append({"host": btn.text.strip(), "url": btn["href"]})

        return {
            **basic_data,
            "image": image,
            "metadata": metadata,
            "system_requirements": sys_reqs,
            "downloads": download_links,
        }

    except Exception as e:
        print(f"[SteamUnderground] Detail scrape error {url}: {e}")
        return None


async def run_scraper(query: str):
    """
    Main entry point. Runs Sync Search in a thread, then Async Details.
    """
    # 1. Run the blocking search in a thread
    basic_results = await asyncio.to_thread(search_game_sync, query)

    if not basic_results:
        return []

    # 2. Fetch details concurrently
    async with aiohttp.ClientSession() as session:
        tasks = [get_game_details(session, game) for game in basic_results]
        detailed_data = await asyncio.gather(*tasks)

    # Filter out failed scrapes
    return [x for x in detailed_data if x is not None]
