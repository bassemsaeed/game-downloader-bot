import asyncio
import aiohttp
import requests
import json
from bs4 import BeautifulSoup

BASE_URL = "https://gamebounty.world"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://gamebounty.world/",
    "X-Requested-With": "XMLHttpRequest",
}


def search_game_sync(query):
    """
    BLOCKING function.
    1. Fetches homepage to get the current Next.js 'buildId'.
    2. Parses the game list from the hydration data.
    """
    print(f"[Sync] Handshaking with {BASE_URL}...")
    try:
        response = requests.get(BASE_URL, headers=HEADERS)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        data_script = soup.find("script", id="__NEXT_DATA__")

        if not data_script:
            print("[Error] Could not find __NEXT_DATA__ script.")
            return []

        # Parse the Next.js Data
        next_data = json.loads(data_script.string)

        # 1. Extract Build ID (Crucial for constructing the JSON API URL)
        build_id = next_data.get("buildId")
        if not build_id:
            print("[Error] Could not extract buildId.")
            return []

        # 2. Get Game List
        all_games = (
            next_data.get("props", {}).get("pageProps", {}).get("initialGames", [])
        )

        results = []
        query_lower = query.lower()

        print(
            f"[Sync] Database loaded (Build: {build_id}). Searching {len(all_games)} games for '{query}'..."
        )

        for game in all_games:
            title = game.get("Title", "Unknown Title")
            slug = game.get("Slug")

            if query_lower in title.lower():
                # We pass the build_id to the async worker
                results.append(
                    {
                        "title": title,
                        "slug": slug,
                        "build_id": build_id,
                        "source": "GameBounty",
                        "cover_image": game.get("Banner"),
                        "version": game.get("version"),
                        "overview": game.get("MiniDescription"),
                    }
                )

        return results

    except Exception as e:
        print(f"[Sync] Error: {e}")
        return []


async def get_game_details(session, basic_data):
    """
    ASYNC function.
    Fetches the hidden Next.js JSON API to get clean data without HTML parsing.
    """
    slug = basic_data["slug"]
    build_id = basic_data["build_id"]

    # Construct the internal API URL based on the user's discovery
    # Pattern: https://gamebounty.world/_next/data/{buildId}/default/download/{slug}.json
    api_url = (
        f"{BASE_URL}/_next/data/{build_id}/default/download/{slug}.json?slug={slug}"
    )

    try:
        async with session.get(api_url, headers=HEADERS) as response:
            if response.status != 200:
                print(f"[Error] API request failed for {slug}: {response.status}")
                return basic_data  # Return basic info if details fail

            json_data = await response.json()

        # Navigate JSON structure: pageProps -> post (or serverPostData)
        props = json_data.get("pageProps", {})

        # GameBounty sometimes uses 'post' and sometimes 'serverPostData'
        post = props.get("post") or props.get("serverPostData") or {}
        container = props.get("customContainerInfo") or props.get("containerInfo") or {}

        # 1. Clean Metadata
        genres = post.get("genres", [])
        if isinstance(genres, str):
            # "Adventure, Casual" -> ["Adventure", "Casual"]
            genres = [g.strip() for g in genres.split(",")]

        metadata = {
            "description": post.get("minidescription"),
            "developer": post.get("developer"),
            "publisher": post.get("publisher"),
            "release_date": post.get("created_at"),
            "updated_at": post.get("updated_at"),
            "genres": genres,
            "steam_url": post.get("steam_shop"),
        }

        # 2. System Requirements (Parsed from JSON string inside JSON)
        sys_reqs = {}
        reqs_raw = post.get("system_requirements")
        if reqs_raw and isinstance(reqs_raw, str):
            try:
                # Remove HTML tags from the reqs strings
                parsed_reqs = json.loads(reqs_raw)
                for key, val in parsed_reqs.items():
                    # Simple strip tags
                    text = BeautifulSoup(val, "html.parser").get_text(" ", strip=True)
                    sys_reqs[key] = text
            except:
                sys_reqs = {"raw": reqs_raw}

        # 3. Downloads (From customContainerInfo -> mirrors)
        downloads = []
        mirrors = container.get("mirrors", [])

        if mirrors:
            for mirror in mirrors:
                host_name = mirror.get("name", "Unknown")
                links = mirror.get("links", [])
                for link in links:
                    downloads.append(
                        {
                            "host": host_name,
                            "url": link.get("url"),
                            "status": link.get("status", "unknown"),
                        }
                    )

        # 4. Fallback: If mirrors missing in JSON (rare), try extracting form HTML description
        # (GameBounty sometimes puts links in the HTML description for older posts)
        if not downloads and "description" in post:
            desc_soup = BeautifulSoup(post["description"], "html.parser")
            for a in desc_soup.find_all("a", href=True):
                if "steam" not in a["href"]:
                    downloads.append({"host": "External", "url": a["href"]})

        return {
            "title": basic_data["title"],
            "source": "GameBounty",
            "url": f"{BASE_URL}/download/{slug}",  # Public URL
            "cover_image": basic_data["cover_image"],
            "version": basic_data["version"],
            "metadata": metadata,
            "system_requirements": sys_reqs,
            "downloads": downloads,
        }

    except Exception as e:
        print(f"[Async] Error processing {slug}: {e}")
        return basic_data


async def run_scraper(query: str):
    """
    Main Entry Point.
    """
    # 1. Sync Search
    basic_results = await asyncio.to_thread(search_game_sync, query)

    if not basic_results:
        print("No results found.")
        return []

    print(f"Found {len(basic_results)} matches. Fetching full data via Next.js API...")

    # 2. Async Details
    async with aiohttp.ClientSession() as session:
        tasks = [get_game_details(session, game) for game in basic_results]
        detailed_data = await asyncio.gather(*tasks)

    # Filter None types
    return [x for x in detailed_data if x]


# --- Usage Example ---
if __name__ == "__main__":
    results = asyncio.run(run_scraper("Until Then"))
    print(json.dumps(results, indent=2))
