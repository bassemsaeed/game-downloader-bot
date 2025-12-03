import logging
import asyncio
import random
import os
from dotenv import load_dotenv
from collections import Counter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
)

# --- IMPORTS ---
from scrapers import steamuground, ankergames

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
# --- CONFIGURATION ---
TOKEN = BOT_TOKEN  # <--- PASTE TOKEN HERE

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# --- FUN MESSAGES ---
LOADING_PHRASES = [
    "💖 Asking the gaming gods...",
    "🧸 Rummaging through the toy box...",
    "✨ Casting a summoning spell...",
    "💅 Doing a quick hair flip while searching...",
    "🚀 Blasting off to find your game...",
    "🧐 Putting on my detective hat...",
    "🎮 Pressing Start...",
    "⚓ Setting sail for booty...",
]

NO_RESULTS_PHRASES = [
    "🥺 Oopsie! Couldn't find that game.",
    "💔 My heart is broken... 0 results found.",
    "🙈 I looked everywhere but found nothing!",
    "🧐 Are you sure that's the right name?",
]

# --- KEYBOARD BUILDERS ---


def build_providers_keyboard(results):
    """
    LEVEL 1: Shows buttons for sources like 'AnkerGames (3)'
    """
    # Count results per source
    sources = [r.get("source", "Unknown") for r in results]
    counts = Counter(sources)

    keyboard = []
    for source, count in counts.items():
        # Icon logic
        icon = "⚓" if source == "AnkerGames" else "🚂"
        text = f"{icon} {source} ({count})"

        # Callback: "list_source_AnkerGames"
        keyboard.append(
            [InlineKeyboardButton(text, callback_data=f"list_source_{source}")]
        )

    return InlineKeyboardMarkup(keyboard)


def build_game_list_keyboard(results, target_source):
    """
    LEVEL 2: Shows list of games, but ONLY for the selected source.
    """
    keyboard = []

    # We iterate through ALL results to find the ones matching the source.
    # We MUST use the global 'idx' so the view button opens the correct game.
    for idx, game in enumerate(results):
        if game.get("source") == target_source:
            # Clean title
            title = game["title"].replace("Free Download", "").strip()
            title = title[:30] + "..." if len(title) > 30 else title

            # Button: "👾 Game Title" -> "view_12" (Global Index 12)
            keyboard.append(
                [InlineKeyboardButton(f"👾 {title}", callback_data=f"view_{idx}")]
            )

    # Back button goes to Provider Menu
    keyboard.append(
        [InlineKeyboardButton("🔙 Back to Sources", callback_data="show_providers")]
    )

    return InlineKeyboardMarkup(keyboard)


def build_details_keyboard(game, download_links):
    """
    LEVEL 3: Download links + Back button to specific list.
    """
    keyboard = []

    # Add download links
    row = []
    for link in download_links:
        host_name = link["host"]
        url = link["url"]

        icon = "📦"
        if "Torrent" in host_name:
            icon = "🧲"
        elif "Mega" in host_name:
            icon = "☁️"
        elif "Google" in host_name:
            icon = "drive"
        elif "Direct" in host_name:
            icon = "⚡"

        row.append(InlineKeyboardButton(f"{icon} {host_name}", url=url))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Back button: Needs to go back to the SPECIFIC source list
    source = game.get("source", "Unknown")
    keyboard.append(
        [InlineKeyboardButton("🔙 Back to List", callback_data=f"list_source_{source}")]
    )

    return InlineKeyboardMarkup(keyboard)


def format_game_details(game):
    """Formats the game dictionary into a pretty HTML Card."""
    source = game.get("source", "Unknown")
    metadata = game.get("metadata", {})

    # 1. Image
    image_url = game.get("image", "")
    img_html = ""
    if image_url and image_url.startswith("http"):
        img_html = f'<a href="{image_url}">&#8205;</a>'

    # 2. Title
    title = game.get("title", "Unknown Title").replace("Free Download", "").strip()

    # 3. Dynamic Metadata
    if source == "AnkerGames":
        size = metadata.get("size", "N/A")
        rel_date = metadata.get("release_date", "N/A")
        genres = ", ".join(metadata.get("genres", [])[:3])
        meta_block = f"💾 <b>Size:</b> {size}\n📅 <b>Date:</b> {rel_date}\n🏷 <b>Genre:</b> {genres}"
        source_badge = "⚓ <b>AnkerGames</b>"
    else:
        group = metadata.get("release_group", "N/A")
        ver = metadata.get("version", "N/A")
        meta_block = f"🏴‍☠️ <b>Cracked by:</b> {group}\n💿 <b>Version:</b> {ver}"
        source_badge = "🚂 <b>SteamUnderground</b>"

    # 4. Sys Reqs
    reqs_list = game.get("system_requirements", [])
    if reqs_list:
        reqs_clean = "\n".join(
            [
                f"  ▫️ <i>{r.replace('Memory:', 'RAM:').replace('Graphics:', 'GPU:').replace('Processor:', 'CPU:')}</i>"
                for r in reqs_list[:4]
            ]
        )
    else:
        reqs_clean = "  ▫️ <i>See download page</i>"

    text = (
        f"{img_html}"
        f"<b>✨ {title} ✨</b>\n"
        f"──────────────────\n"
        f"{meta_block}\n"
        f"──────────────────\n\n"
        f"<b>💻 System Stats:</b>\n"
        f"{reqs_clean}\n\n"
        f"🔎 Source: {source_badge}\n"
        f"<i>Select a download below! 👇</i>"
    )
    return text


# --- HANDLERS ---


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 <b>Hi {user_name}!</b>\n\n"
        "I'm your personal gaming assistant. 🧚‍♀️\n"
        "I search multiple sites to find the best links for you.\n\n"
        "👇 <b>Type this:</b>\n"
        "<code>/search sims 4</code>",
        parse_mode=constants.ParseMode.HTML,
    )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "✨ You need to type the name! \nExample: <code>/search sims 4</code>",
            parse_mode=constants.ParseMode.HTML,
        )
        return

    query = " ".join(context.args)
    loading_text = random.choice(LOADING_PHRASES)
    status_msg = await update.message.reply_text(
        f"{loading_text}\n<i>(Looking for: {query})</i>",
        parse_mode=constants.ParseMode.HTML,
    )

    # Run Scrapers
    scraper_tasks = [steamuground.run_scraper(query), ankergames.run_scraper(query)]
    results_list_of_lists = await asyncio.gather(*scraper_tasks)
    all_results = [item for sublist in results_list_of_lists for item in sublist]

    if not all_results:
        sad_text = random.choice(NO_RESULTS_PHRASES)
        await status_msg.edit_text(sad_text, parse_mode=constants.ParseMode.HTML)
        return

    # Store results
    context.user_data["last_results"] = all_results

    # SHOW LEVEL 1: Provider Menu
    await status_msg.edit_text(
        f"🎉 <b>I found {len(all_results)} games!</b>\n"
        "<i>Where should we look first?</i>",
        reply_markup=build_providers_keyboard(all_results),
        parse_mode=constants.ParseMode.HTML,
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    results = context.user_data.get("last_results", [])

    if not results:
        await query.edit_message_text("⌛ Session expired. Please search again!")
        return

    # --- LEVEL 1: SHOW PROVIDERS ---
    if data == "show_providers":
        await query.edit_message_text(
            f"🎉 <b>Results found: {len(results)}</b>\n<i>Select a source:</i>",
            reply_markup=build_providers_keyboard(results),
            parse_mode=constants.ParseMode.HTML,
        )

    # --- LEVEL 2: SHOW GAME LIST FOR SPECIFIC SOURCE ---
    elif data.startswith("list_source_"):
        source_name = data.replace("list_source_", "")

        # Count games for this source for the header
        count = sum(1 for g in results if g["source"] == source_name)

        await query.edit_message_text(
            f"📂 <b>{source_name} Results</b> ({count} found)\n"
            "<i>Select a game to view details:</i>",
            reply_markup=build_game_list_keyboard(results, source_name),
            parse_mode=constants.ParseMode.HTML,
        )

    # --- LEVEL 3: SHOW GAME DETAILS ---
    elif data.startswith("view_"):
        try:
            index = int(data.split("_")[1])
            game = results[index]

            details_text = format_game_details(game)
            # We pass the 'game' object to the keyboard builder so it knows where to go back to
            buttons = build_details_keyboard(game, game.get("downloads", []))

            await query.edit_message_text(
                text=details_text,
                reply_markup=buttons,
                parse_mode=constants.ParseMode.HTML,
                disable_web_page_preview=False,
            )

        except (IndexError, ValueError) as e:
            logging.error(f"Error viewing game: {e}")
            await query.edit_message_text("⚠ Error loading game.")


# --- MAIN RUNNER ---
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🤖 Bot is running...")
    app.run_polling()
