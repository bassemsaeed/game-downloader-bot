# sarcastic_tele_bot_inline_v2.py
import logging
import asyncio
import random
import os
import re
import math
import uuid
from dotenv import load_dotenv
from collections import Counter

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    constants,
    InputMediaAnimation,
    InputFile,
    BotCommand,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from telegram.ext import (
    Application,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    ApplicationBuilder,
    InlineQueryHandler,
)
from telegram.request import HTTPXRequest

# --- IMPORTS: Your scrapers ---
from scrapers import steamuground, ankergames, gamebounty

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# --- CONFIG ---
PAGE_SIZE = 8
TOKEN = BOT_TOKEN

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- GLOBAL CACHE ---
MEDIA_CACHE = {"loading": None, "celebrate": None, "fail": None}

# --- TEXT ASSETS ---
LOADING_PHRASES = [
    "📡 Pinging Elon's satellites...",
    "💀 Waking up the server hamsters...",
    "🥃 Hold my beer...",
    "👾 Brute-forcing the mainframe...",
    "🐌 Loading... (blame your wifi)",
    "🔍 Scouring the dark web...",
]

NO_RESULTS_PHRASES = [
    "📉 Mission failed. We'll get 'em next time.",
    "💀 404: Game not found (or I'm just lazy).",
    "🚫 Empty. The void stares back.",
    "👀 Never heard of that. Is it indie?",
    "🏳️ I surrender. No results.",
]

TOASTS = [
    "Hang tight...",
    "Loading pixels...",
    "Flipping pages...",
    "Processing...",
    "Zoom zoom...",
]


# --- HELPERS ---
def _sanitize_callback(text: str) -> str:
    s = re.sub(r"\s+", "_", text)
    s = re.sub(r"[^0-9A-Za-z_\-]", "", s)
    return s[:32]


def _find_source_by_sanitized(results, sanitized):
    for r in results:
        src = r.get("source", "Unknown")
        if _sanitize_callback(src) == sanitized:
            return src
    return sanitized


# --- KEYBOARD BUILDERS ---
def build_providers_keyboard(results):
    sources = [r.get("source", "Unknown") for r in results]
    counts = Counter(sources)
    keyboard = []

    for source, count in counts.items():
        if "anker" in source.lower():
            icon = "⚓"
        elif "bounty" in source.lower():
            icon = "💎"
        else:
            icon = "🚂"

        text = f"{icon} {source} • {count}"
        sanitized = _sanitize_callback(source)
        keyboard.append([InlineKeyboardButton(text, callback_data=f"ls_{sanitized}_0")])
    return InlineKeyboardMarkup(keyboard)


def build_paginated_game_list(results, target_source, page=0):
    source_games = []
    for idx, g in enumerate(results):
        if g.get("source") == target_source:
            source_games.append({"game": g, "original_index": idx})

    total_items = len(source_games)
    total_pages = math.ceil(total_items / PAGE_SIZE)

    if page >= total_pages:
        page = total_pages - 1
    if page < 0:
        page = 0
    if total_pages == 0:
        page = 0

    start_idx = page * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    current_items = source_games[start_idx:end_idx]

    keyboard = []

    for item in current_items:
        game = item["game"]
        real_idx = item["original_index"]
        title = game.get("title", "Untitled").replace("Free Download", "").strip()
        title = title[:28] + ".." if len(title) > 28 else title
        keyboard.append(
            [InlineKeyboardButton(f"👾 {title}", callback_data=f"v_{real_idx}_{page}")]
        )

    nav_row = []
    sanitized_source = _sanitize_callback(target_source)

    if total_pages > 1:
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    "⬅️", callback_data=f"ls_{sanitized_source}_{page - 1}"
                )
            )
        nav_row.append(
            InlineKeyboardButton(
                f"• {page + 1} / {total_pages} •", callback_data="noop"
            )
        )
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    "➡️", callback_data=f"ls_{sanitized_source}_{page + 1}"
                )
            )
        keyboard.append(nav_row)

    keyboard.append(
        [InlineKeyboardButton("🔙 Back to Sources", callback_data="show_providers")]
    )
    return InlineKeyboardMarkup(keyboard)


def build_download_keyboard(download_links, include_back_btn=True, back_data=None):
    """Refactored to be reusable for Inline mode (no back button needed there)."""
    keyboard = []
    row = []

    for link in download_links:
        host_name = link.get("host", "Link")
        url = link.get("url")
        if not url:
            continue

        lower = host_name.lower()
        icon = "📦"
        if "torrent" in lower:
            icon = "🧲"
        elif "mega" in lower:
            icon = "☁️"
        elif "google" in lower:
            icon = "🟢"
        elif "direct" in lower:
            icon = "⚡"
        elif "gofile" in lower:
            icon = "📂"
        elif "pixeldrain" in lower:
            icon = "🎨"
        elif "1fichier" in lower:
            icon = "🐟"

        row.append(InlineKeyboardButton(f"{icon} {host_name}", url=url))
        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    if include_back_btn and back_data:
        keyboard.append(
            [InlineKeyboardButton("🔙 Back to List", callback_data=back_data)]
        )

    return InlineKeyboardMarkup(keyboard)


# --- MODERN FORMATTING ---
def format_game_details(game):
    source = game.get("source", "Unknown")
    metadata = game.get("metadata", {})
    image_url = game.get("image") or game.get("cover_image") or ""

    img_html = (
        f'<a href="{image_url}">&#8205;</a>'
        if image_url and image_url.startswith("http")
        else ""
    )
    title = game.get("title", "Unknown").replace("Free Download", "").strip()

    if source == "AnkerGames":
        size = metadata.get("size", "N/A")
        rel_date = metadata.get("release_date", "N/A")
        genres = ", ".join(metadata.get("genres", [])[:3])
        meta_block = f"<blockquote>💾 <b>Size:</b> {size}\n📅 <b>Date:</b> {rel_date}\n🏷 <b>Genre:</b> {genres}</blockquote>"
        source_badge = "⚓ <b>AnkerGames</b>"
    elif source == "GameBounty":
        dev = metadata.get("developer", "N/A")
        ver = game.get("version") or metadata.get("version", "N/A")
        genres = ", ".join(metadata.get("genres", [])[:3])
        meta_block = f"<blockquote>👨‍💻 <b>Dev:</b> {dev}\n🏷 <b>Genre:</b> {genres}\n💿 <b>Ver:</b> {ver}</blockquote>"
        source_badge = "💎 <b>GameBounty</b>"
    else:
        group = metadata.get("release_group", "N/A")
        ver = metadata.get("version", "N/A")
        meta_block = (
            f"<blockquote>🏴‍☠️ <b>Crack:</b> {group}\n💿 <b>Ver:</b> {ver}</blockquote>"
        )
        source_badge = "🚂 <b>SteamUnderground</b>"

    reqs_data = game.get("system_requirements", [])
    reqs_clean = "<i>Check download page</i>"
    if isinstance(reqs_data, list) and reqs_data:
        reqs_clean = "\n".join([f"• {r}" for r in reqs_data[:5]])
    elif isinstance(reqs_data, dict) and reqs_data:
        raw_min = reqs_data.get("minimum", "")
        clean_text = re.sub(r"<[^>]+>", "", raw_min).replace("Minimum:", "").strip()
        reqs_clean = clean_text[:400]

    text = (
        f"{img_html}\n"
        f"<b>{title}</b>\n"
        f"{meta_block}\n"
        f"<b>💻 System Requirements:</b>\n"
        f"<blockquote expandable>{reqs_clean}</blockquote>\n\n"
        f"🔎 Source: {source_badge}\n\n"
        f"<span class='tg-spoiler'>👇 UNLOCK LINKS BELOW 👇</span>"
    )
    return text


# --- MESSAGING LOGIC ---
async def finalize_message(bot, chat_id, message_id, mode, caption, keyboard=None):
    gif_path = f"{mode}.gif"
    fallback_url = "https://media.giphy.com/media/26FPqut4tYkz5v3Su/giphy.gif"

    media_input = MEDIA_CACHE.get(mode)
    f_handle = None

    if not media_input:
        if os.path.exists(gif_path):
            f_handle = open(gif_path, "rb")
            media_input = InputFile(f_handle)
        else:
            media_input = fallback_url

    try:
        input_media = InputMediaAnimation(
            media=media_input, caption=caption, parse_mode=constants.ParseMode.HTML
        )
        msg = await bot.edit_message_media(
            chat_id=chat_id,
            message_id=message_id,
            media=input_media,
            reply_markup=keyboard,
        )
        if not MEDIA_CACHE.get(mode) and msg.animation:
            MEDIA_CACHE[mode] = msg.animation.file_id

    except Exception:
        try:
            await bot.delete_message(chat_id, message_id)
        except:
            pass

        if f_handle:
            f_handle.seek(0)

        msg = await bot.send_animation(
            chat_id=chat_id,
            animation=media_input,
            caption=caption,
            reply_markup=keyboard,
            parse_mode=constants.ParseMode.HTML,
        )
        if not MEDIA_CACHE.get(mode) and msg.animation:
            MEDIA_CACHE[mode] = msg.animation.file_id
    finally:
        if f_handle:
            f_handle.close()


# --- HANDLERS ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔎 Search Inline", switch_inline_query_current_chat=""
                )
            ]
        ]
    )
    await update.message.reply_text(
        f"<b>👋 Yo, {user}.</b>\n\n"
        "I'm your pirate librarian. I find games.\n\n"
        "<b>Commands:</b>\n"
        "<code>/search name</code> - Classic Search\n"
        "<code>@BotName name</code> - Inline Search (Any chat)",
        reply_markup=kb,
        parse_mode=constants.ParseMode.HTML,
    )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ <b>Syntax:</b> <code>/search Elden Ring</code>",
            parse_mode=constants.ParseMode.HTML,
        )
        return

    query = " ".join(context.args)
    load_caption = (
        f"<b>{random.choice(LOADING_PHRASES)}</b>\n<code>Query: {query}</code>"
    )

    media = (
        MEDIA_CACHE.get("loading")
        or "https://media.giphy.com/media/3oEjI6SIIHBdRxXI40/giphy.gif"
    )
    if not MEDIA_CACHE.get("loading") and os.path.exists("loading.gif"):
        media = open("loading.gif", "rb")

    msg = await update.message.reply_animation(
        animation=media, caption=load_caption, parse_mode=constants.ParseMode.HTML
    )
    if not MEDIA_CACHE.get("loading") and hasattr(media, "read"):
        media.close()
        if msg.animation:
            MEDIA_CACHE["loading"] = msg.animation.file_id

    tasks = [
        steamuground.run_scraper(query),
        ankergames.run_scraper(query),
        gamebounty.run_scraper(query),
    ]
    results_raw = await asyncio.gather(*tasks, return_exceptions=True)
    all_results = []
    for r in results_raw:
        if isinstance(r, list):
            all_results.extend(r)

    if not all_results:
        await finalize_message(
            context.bot,
            msg.chat_id,
            msg.message_id,
            "fail",
            f"<b>{random.choice(NO_RESULTS_PHRASES)}</b>",
        )
        return

    context.user_data["last_results"] = all_results
    success_text = f"🎉 <b>Success.</b> Found {len(all_results)} titles."
    await finalize_message(
        context.bot, msg.chat_id, msg.message_id, "celebrate", success_text
    )

    await context.bot.send_message(
        chat_id=msg.chat_id,
        text="👇 <b>Choose your provider:</b>",
        reply_markup=build_providers_keyboard(all_results),
        parse_mode=constants.ParseMode.HTML,
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    results = context.user_data.get("last_results", [])

    if not results and data != "noop":
        await query.answer("⚠️ Session expired. Search again.", show_alert=True)
        return

    if data == "noop":
        await query.answer(
            random.choice(["Stop poking me.", "Just a label.", "I do nothing."])
        )
        return

    try:
        if data == "show_providers":
            await query.answer("Back to roots...")
            await query.edit_message_text(
                f"🎉 <b>Found {len(results)} games.</b>\n👇 <b>Choose your provider:</b>",
                reply_markup=build_providers_keyboard(results),
                parse_mode=constants.ParseMode.HTML,
            )
            return

        if data.startswith("ls_"):
            parts = data.split("_")
            page = int(parts[-1])
            sanitized_source = "_".join(parts[1:-1])
            await query.answer(random.choice(TOASTS))

            source_name = _find_source_by_sanitized(results, sanitized_source)
            count = sum(1 for g in results if g.get("source") == source_name)

            await query.edit_message_text(
                f"📂 <b>{source_name}</b>\nFound: {count} titles\n<i>Page {page + 1}</i>",
                reply_markup=build_paginated_game_list(results, source_name, page),
                parse_mode=constants.ParseMode.HTML,
            )
            return

        if data.startswith("v_"):
            parts = data.split("_")
            idx = int(parts[1])
            page = int(parts[2])
            await query.answer("Fetching data...")

            game = results[idx]
            text = format_game_details(game)

            # Back data needed for normal mode
            source = game.get("source", "Unknown")
            sanitized_source = _sanitize_callback(source)
            back_data = f"ls_{sanitized_source}_{page}"

            kb = build_download_keyboard(game.get("downloads", []), True, back_data)

            await query.edit_message_text(
                text=text,
                reply_markup=kb,
                parse_mode=constants.ParseMode.HTML,
                disable_web_page_preview=False,
            )
            return

    except Exception as e:
        logger.error(f"Button Error: {e}")
        await query.answer("🔥 Glitch in the matrix.", show_alert=True)


# --- INLINE QUERY HANDLER ---
async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles @BotName search queries in any chat.
    """
    query = update.inline_query.query.strip()

    if len(query) < 3:
        # Don't search for tiny strings, just return empty or help
        return

    # Run scrapers (reusing logic)
    tasks = [
        steamuground.run_scraper(query),
        ankergames.run_scraper(query),
        gamebounty.run_scraper(query),
    ]

    # We await the results. Note: Inline mode has a strict timeout.
    # If scrapers are too slow, Telegram will show a network error icon.
    results_raw = await asyncio.gather(*tasks, return_exceptions=True)
    all_results = []
    for r in results_raw:
        if isinstance(r, list):
            all_results.extend(r)

    # Limit to top 30 to keep it fast
    all_results = all_results[:30]

    articles = []
    for i, game in enumerate(all_results):
        title = game.get("title", "Unknown Title").replace("Free Download", "")
        source = game.get("source", "Unknown")
        image_url = (
            game.get("image")
            or game.get("cover_image")
            or "https://via.placeholder.com/150"
        )

        # Format the content that will be sent
        message_text = format_game_details(game)

        # Build Keyboard (Only download links, no Back buttons)
        kb = build_download_keyboard(game.get("downloads", []), include_back_btn=False)

        article = InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title=title,
            description=f"Source: {source}",
            thumbnail_url=image_url
            if image_url.startswith("http")
            else "https://img.icons8.com/color/48/console.png",
            input_message_content=InputTextMessageContent(
                message_text,
                parse_mode=constants.ParseMode.HTML,
                disable_web_page_preview=False,
            ),
            reply_markup=kb,
        )
        articles.append(article)

    await update.inline_query.answer(articles, cache_time=300)


# --- INIT ---
async def post_init(application: Application):
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Wake me up"),
            BotCommand("search", "Find a game"),
            BotCommand("help", "Emotional Support"),
        ]
    )
    print("✅ Commands set successfully.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("Missing BOT_TOKEN in .env")

    request = HTTPXRequest(connection_pool_size=10, read_timeout=40, write_timeout=40)

    app = (
        ApplicationBuilder().token(TOKEN).request(request).post_init(post_init).build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler(["search", "s"], search_command))
    app.add_handler(CommandHandler("help", start_command))

    # ADD INLINE HANDLER
    app.add_handler(InlineQueryHandler(inline_query))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_error_handler(error_handler)

    print("🚀 Sarcastic Bot Online (Inline + Modern Mode)...")
    app.run_polling()
