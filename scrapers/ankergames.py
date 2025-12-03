import asyncio
import aiohttp
import requests
import re
import json
from urllib.parse import unquote
from bs4 import BeautifulSoup

# --- Configuration ---
BASE_URL = "https://ankergames.net"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://ankergames.net/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# --- Helper Functions (Internal) ---


def _clean_text(text):
    if not text:
        return ""
    return " ".join(text.split())


def _extract_system_reqs_list(soup):
    """Parses system reqs and returns a list of strings 'Key: Value'."""
    reqs = []
    target_header = None
    # Robust header finding
    for h2 in soup.find_all("h2"):
        text = h2.get_text().lower()
        if "system" in text and "requirements" in text:
            target_header = h2
            break

    if target_header:
        card = target_header.find_parent("div", class_="shadow-xl")
        if card:
            dts = card.find_all("dt")
            for dt in dts:
                key = _clean_text(dt.get_text()).replace("*", "").strip()
                dd = dt.find_next_sibling("dd")
                if dd:
                    val = _clean_text(dd.get_text())
                    reqs.append(f"{key}: {val}")
    return reqs


async def _resolve_download_link(session, download_endpoint, csrf_token):
    """
    Internal Async Helper: POSTs to API -> Gets Intermediate Page -> Extracts Final Link
    """
    if not csrf_token:
        return None

    post_headers = {
        **HEADERS,
        "X-CSRF-TOKEN": csrf_token,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/json",
    }
    payload = {"g-recaptcha-response": "development-mode"}

    try:
        # 1. POST to generate URL
        async with session.post(
            download_endpoint, headers=post_headers, json=payload
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()

        if not data.get("success"):
            return None

        intermediate_url = data.get("download_url")

        # 2. GET the waiting room / intermediate page
        async with session.get(intermediate_url) as resp:
            html = await resp.text()

        # 3. Extract final link via Regex or Button
        match = re.search(r"downloadPage\('([^']+)'", html)
        if match:
            return unquote(match.group(1))

        soup = BeautifulSoup(html, "html.parser")
        btn = soup.find("a", attrs={"aria-label": "Download Now"})
        if btn and btn.get("href"):
            return btn.get("href")

    except Exception as e:
        print(f"[AnkerGames] Resolve error: {e}")
        return None


# --- Main Interface Functions ---


def search_game_sync(query):
    """
    BLOCKING function using 'requests' to perform the search.
    """
    search_url = f"{BASE_URL}/search/{query}"
    try:
        response = requests.get(search_url, headers=HEADERS)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        results = []

        # Target the specific search result card structure
        cards = soup.select(".relative.group.cursor-pointer:not(.animate-pulse)")

        for card in cards:
            link_tag = card.find("a", href=True)
            title_tag = card.find("h3")

            if link_tag and title_tag:
                results.append(
                    {
                        "title": title_tag.text.strip(),
                        "url": link_tag["href"],
                        "source": "AnkerGames",
                    }
                )

        return results

    except Exception as e:
        print(f"[AnkerGames] Search error: {e}")
        return []


async def get_game_details(session, basic_data):
    """
    ASYNC function. Fetches details, parses metadata, and resolves specific download links.
    """
    url = basic_data["url"]
    try:
        async with session.get(url, headers=HEADERS) as response:
            response.raise_for_status()
            html_content = await response.text()

        soup = BeautifulSoup(html_content, "html.parser")

        # 0. Extract CSRF Token (Essential for resolving downloads)
        csrf_token = None
        meta_csrf = soup.find("meta", attrs={"name": "csrf-token"})
        if meta_csrf:
            csrf_token = meta_csrf.get("content")

        # 1. Cover Image
        img_tag = soup.select_one(r".max-w-\[16rem\] picture img")
        image = None
        if img_tag:
            image = img_tag.get("src")

        # 2. Metadata (Size, Date, Publisher, Genre)
        metadata = {
            "size": "N/A",
            "release_date": "N/A",
            "publisher": "N/A",
            "genres": [],
        }

        # Size from header
        header_stats = soup.select(".flex.items-center.text-xs span")
        for stat in header_stats:
            txt = stat.get_text()
            if "GB" in txt or "MB" in txt:
                metadata["size"] = txt.strip()
                break

        # Detailed metadata from grid
        meta_grids = soup.select(r".grid.sm\:flex.gap-x-3")
        for grid in meta_grids:
            label_div = grid.find("div", class_="min-w-[150px]")
            if not label_div:
                continue
            label = label_div.get_text(strip=True)
            value_div = grid.find("div", class_="font-medium")

            if "Genre" in label and value_div:
                metadata["genres"] = [
                    _clean_text(a.get_text()) for a in value_div.find_all("a")
                ]
            elif "Released" in label and value_div:
                metadata["release_date"] = _clean_text(value_div.get_text())
            elif "Publisher" in label and value_div:
                metadata["publisher"] = _clean_text(value_div.get_text())

        # 3. System Requirements (List format)
        sys_reqs = _extract_system_reqs_list(soup)

        # 4. Downloads - Extract IDs and Resolve Links
        download_links = []
        modal = soup.find(id="download-modal")

        if modal:
            items = modal.find_all("li")
            for item in items:
                # Find provider name
                provider_div = item.find("div")
                host = (
                    _clean_text(provider_div.get_text()) if provider_div else "Direct"
                )

                # Find ID
                btn = item.find("a", attrs={"@click.prevent": True})
                if btn:
                    click_attr = btn["@click.prevent"]
                    match = re.search(r"generateDownloadUrl\((\d+)\)", click_attr)
                    if match:
                        dl_id = match.group(1)
                        endpoint = f"{BASE_URL}/generate-download-url/{dl_id}"

                        # RESOLVE LINK LOGIC
                        # We specifically try to resolve the "Direct" link immediately
                        final_url = None
                        if "Direct" in host:
                            final_url = await _resolve_download_link(
                                session, endpoint, csrf_token
                            )

                        # Fallback to endpoint if resolution fails or not attempted
                        download_links.append(
                            {
                                "host": host,
                                "url": final_url if final_url else endpoint,
                                "resolved": bool(final_url),
                            }
                        )

        return {
            **basic_data,
            "image": image,
            "metadata": metadata,
            "system_requirements": sys_reqs,
            "downloads": download_links,
        }

    except Exception as e:
        print(f"[AnkerGames] Detail scrape error {url}: {e}")
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


# --- Example Usage (Internal Test) ---
if __name__ == "__main__":
    import time

    async def main():
        start = time.time()
        results = await run_scraper("fifa")
        print(json.dumps(results, indent=2))
        print(f"Finished in {time.time() - start:.2f}s")

    asyncio.run(main())

