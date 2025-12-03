# sarcastic_tele_bot_fast_full_info.py
import logging
import asyncio
import random
import os
import re
from dotenv import load_dotenv
from collections import Counter
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    constants,
    InputMediaAnimation,
    InputFile,
)
from telegram.ext import Application, ContextTypes, CommandHandler, CallbackQueryHandler
from telegram.request import HTTPXRequest

# --- IMPORTS: Your scrapers ---
from scrapers import steamuground, ankergames, gamebounty

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
TOKEN = BOT_TOKEN

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- GLOBAL CACHE ---
# Stores file_ids so we don't have to upload files every time
MEDIA_CACHE = {"loading": None, "celebrate": None, "fail": None}

# --- Messages ---
LOADING_PHRASES = [
    "📡 Pinging satellites...",
    "💀 Waking up the hamsters...",
    "🥃 One sec...",
    "👾 Hacking the mainframe...",
    "🐌 Loading... internet is slow.",
    "🔍 Searching...",
]

NO_RESULTS_PHRASES = [
    "📉 Mission failed.",
    "💀 404: Game not found.",
    "🚫 Empty. The void stares back.",
    "👀 Never heard of that.",
    "🏳️ I surrender.",
]


# --- Helpers ---
def _sanitize_callback(text: str) -> str:
    s = re.sub(r"\s+", "_", text)
    s = re.sub(r"[^0-9A-Za-z_\-]", "", s)
    return s[:64]


def _find_source_by_sanitized(results, sanitized):
    for r in results:
        src = r.get("source", "Unknown")
        if _sanitize_callback(src) == sanitized:
            return src
    return sanitized.replace("_", " ")


def build_providers_keyboard(results):
    sources = [r.get("source", "Unknown") for r in results]
    counts = Counter(sources)
    keyboard = []
    for source, count in counts.items():
        if source == "AnkerGames":
            icon = "⚓"
        elif source == "GameBounty":
            icon = "💎"
        else:
            icon = "🚂"
        text = f"{icon} {source} ({count})"
        keyboard.append(
            [
                InlineKeyboardButton(
                    text, callback_data=f"list_source_{_sanitize_callback(source)}"
                )
            ]
        )
    return InlineKeyboardMarkup(keyboard)


def build_game_list_keyboard(results, target_source):
    keyboard = []
    for idx, game in enumerate(results):
        if game.get("source") == target_source:
            title = game.get("title", "Untitled").replace("Free Download", "").strip()
            title = title[:30] + "..." if len(title) > 30 else title
            keyboard.append(
                [InlineKeyboardButton(f"👾 {title}", callback_data=f"view_{idx}")]
            )
    keyboard.append(
        [InlineKeyboardButton("🔙 Back to Sources", callback_data="show_providers")]
    )
    return InlineKeyboardMarkup(keyboard)


def build_details_keyboard(game, download_links):
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
    source = game.get("source", "Unknown")
    keyboard.append(
        [
            InlineKeyboardButton(
                "🔙 Back to List",
                callback_data=f"list_source_{_sanitize_callback(source)}",
            )
        ]
    )
    return InlineKeyboardMarkup(keyboard)


# --- RESTORED: Full Detailed Formatting ---
def format_game_details(game):
    source = game.get("source", "Unknown")
    metadata = game.get("metadata", {})
    image_url = game.get("image") or game.get("cover_image") or ""

    # Invisible link for image preview
    img_html = (
        f'<a href="{image_url}">&#8205;</a>\n'
        if image_url and image_url.startswith("http")
        else ""
    )
    title = game.get("title", "Unknown Title").replace("Free Download", "").strip()

    if source == "AnkerGames":
        size = metadata.get("size", "N/A")
        rel_date = metadata.get("release_date", "N/A")
        genres = ", ".join(metadata.get("genres", [])[:3])
        meta_block = f"💾 <b>Size:</b> {size}\n📅 <b>Date:</b> {rel_date}\n🏷 <b>Genre:</b> {genres}"
        source_badge = "⚓ <b>AnkerGames</b>"
    elif source == "GameBounty":
        dev = metadata.get("developer", "N/A")
        ver = game.get("version") or metadata.get("version", "N/A")
        genres = ", ".join(metadata.get("genres", [])[:3])
        meta_block = (
            f"👨‍💻 <b>Dev:</b> {dev}\n🏷 <b>Genre:</b> {genres}\n💿 <b>Ver:</b> {ver}"
        )
        source_badge = "💎 <b>GameBounty</b>"
    else:
        group = metadata.get("release_group", "N/A")
        ver = metadata.get("version", "N/A")
        meta_block = f"🏴‍☠️ <b>Cracked by:</b> {group}\n💿 <b>Version:</b> {ver}"
        source_badge = "🚂 <b>SteamUnderground</b>"

    # System Requirements Parsing
    reqs_data = game.get("system_requirements", [])
    reqs_clean = "▫️ <i>See download page</i>"
    if isinstance(reqs_data, list) and reqs_data:
        reqs_clean = "\n".join(
            [
                f"  ▫️ <i>{r.replace('Memory:', 'RAM:').replace('Graphics:', 'GPU:').replace('Processor:', 'CPU:')}</i>"
                for r in reqs_data[:4]
            ]
        )
    elif isinstance(reqs_data, dict) and reqs_data:
        raw_min = reqs_data.get("minimum", "")
        if raw_min:
            clean_text = raw_min.replace("<strong>Minimum:</strong>", "").strip()
            if len(clean_text) > 300:
                clean_text = clean_text[:300] + "..."
            reqs_clean = f"  ▫️ <i>{clean_text}</i>"

    text = (
        f"{img_html}"
        f"<b>✨ {title} ✨</b>\n"
        f"──────────────────\n"
        f"{meta_block}\n"
        f"──────────────────\n\n"
        f"<b>💻 System Stats:</b>\n"
        f"{reqs_clean}\n\n"
        f"🔎 Source: {source_badge}\n"
        f"<i>👇 Grab a link below:</i>"
    )
    return text


# --- CORE LOGIC: Unified Message Updater with Cache ---
async def finalize_message(bot, chat_id, message_id, mode, caption, keyboard=None):
    """
    mode: 'celebrate' or 'fail'
    Uses cache to be super fast.
    """
    gif_path = f"{mode}.gif"
    fallback_url = "https://media.giphy.com/media/26FPqut4tYkz5v3Su/giphy.gif"

    media_input = None
    file_handle = None

    # Cache lookup
    if MEDIA_CACHE.get(mode):
        media_input = MEDIA_CACHE[mode]
    elif os.path.exists(gif_path):
        file_handle = open(gif_path, "rb")
        media_input = InputFile(file_handle)
    else:
        media_input = fallback_url

    try:
        # METHOD A: Edit Media (Preferred)
        input_media = InputMediaAnimation(
            media=media_input, caption=caption, parse_mode=constants.ParseMode.HTML
        )
        edited_msg = await bot.edit_message_media(
            chat_id=chat_id,
            message_id=message_id,
            media=input_media,
            reply_markup=keyboard,
        )

        if not MEDIA_CACHE.get(mode) and edited_msg.animation:
            MEDIA_CACHE[mode] = edited_msg.animation.file_id
            logger.info(f"✅ Cached {mode} GIF ID: {MEDIA_CACHE[mode]}")

    except Exception as e:
        logger.warning(f"Edit failed ({e}), falling back to fresh send.")
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except:
            pass

        if file_handle:
            file_handle.seek(0)

        try:
            sent_msg = await bot.send_animation(
                chat_id=chat_id,
                animation=media_input,
                caption=caption,
                reply_markup=keyboard,
                parse_mode=constants.ParseMode.HTML,
                read_timeout=30,
                write_timeout=30,
            )
            if not MEDIA_CACHE.get(mode) and sent_msg.animation:
                MEDIA_CACHE[mode] = sent_msg.animation.file_id
                logger.info(f"✅ Cached {mode} GIF ID: {MEDIA_CACHE[mode]}")
        except Exception as e2:
            logger.error(f"FATAL: Could not send animation: {e2}")
            await bot.send_message(
                chat_id,
                f"{caption}",
                reply_markup=keyboard,
                parse_mode=constants.ParseMode.HTML,
            )

    finally:
        if file_handle:
            file_handle.close()


# --- Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name if update.effective_user else "friend"
    await update.message.reply_text(
        f"👋 <b>Hey {user_name}.</b>\n\n"
        "I'm your sarcastic game-finding assistant.\n"
        "I search <b>GameBounty</b>, <b>Anker</b> & <b>SteamUnderground</b>.\n\n"
        "👇 <b>Command:</b>\n"
        "<code>/search elden ring</code>",
        parse_mode=constants.ParseMode.HTML,
    )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ Type a name. Example: <code>/search zelda</code>",
            parse_mode=constants.ParseMode.HTML,
        )
        return

    query = " ".join(context.args)
    loading_text = f"{random.choice(LOADING_PHRASES)}\n<i>(Query: {query})</i>"

    # 1. SEND LOADING
    loading_media = MEDIA_CACHE.get("loading")
    f_handle = None

    if not loading_media and os.path.exists("loading.gif"):
        f_handle = open("loading.gif", "rb")
        loading_media = f_handle
    elif not loading_media:
        loading_media = "https://media.giphy.com/media/3oEjI6SIIHBdRxXI40/giphy.gif"

    try:
        loading_msg = await update.message.reply_animation(
            animation=loading_media,
            caption=loading_text,
            parse_mode=constants.ParseMode.HTML,
            read_timeout=20,
            write_timeout=20,
        )
        if not MEDIA_CACHE.get("loading") and loading_msg.animation:
            MEDIA_CACHE["loading"] = loading_msg.animation.file_id
            logger.info(f"✅ Cached loading GIF ID: {MEDIA_CACHE['loading']}")

    except Exception as e:
        logger.error(f"Loading GIF failed: {e}")
        loading_msg = await update.message.reply_text(
            f"⏳ {loading_text}", parse_mode=constants.ParseMode.HTML
        )
    finally:
        if f_handle:
            f_handle.close()

    # 2. RUN SCRAPERS
    scraper_tasks = [
        steamuground.run_scraper(query),
        ankergames.run_scraper(query),
        gamebounty.run_scraper(query),
    ]

    try:
        results_list_of_lists = await asyncio.gather(*scraper_tasks)
        all_results = [item for sublist in results_list_of_lists for item in sublist]
    except Exception:
        all_results = []

    # 3. FINALIZE
    if not all_results:
        sad_text = random.choice(NO_RESULTS_PHRASES)
        await finalize_message(
            context.bot, loading_msg.chat_id, loading_msg.message_id, "fail", sad_text
        )
        return

    context.user_data["last_results"] = all_results
    success_caption = (
        f"🎉 <b>Found {len(all_results)} games.</b>\n<i>Pick your poison:</i>"
    )

    await finalize_message(
        context.bot,
        loading_msg.chat_id,
        loading_msg.message_id,
        "celebrate",
        success_caption,
    )

    # Send menu text separately
    await context.bot.send_message(
        chat_id=loading_msg.chat_id,
        text="👇 <b>Select a Source to view games:</b>",
        reply_markup=build_providers_keyboard(all_results),
        parse_mode=constants.ParseMode.HTML,
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    results = context.user_data.get("last_results", [])

    if not results:
        await query.edit_message_text("⌛ Session expired.")
        return

    if data == "show_providers":
        await query.edit_message_text(
            f"🔥 <b>Found {len(results)} games.</b>\n<i>Pick your poison:</i>",
            reply_markup=build_providers_keyboard(results),
            parse_mode=constants.ParseMode.HTML,
        )
        return

    if data.startswith("list_source_"):
        source_name_sanitized = data.replace("list_source_", "")
        source_name = _find_source_by_sanitized(results, source_name_sanitized)
        count = sum(1 for g in results if g.get("source") == source_name)
        await query.edit_message_text(
            f"📂 <b>{source_name}</b> ({count} found)\n<i>Drill down:</i>",
            reply_markup=build_game_list_keyboard(results, source_name),
            parse_mode=constants.ParseMode.HTML,
        )
        return

    if data.startswith("view_"):
        try:
            index = int(data.split("_", 1)[1])
            game = results[index]
            details_text = format_game_details(game)
            buttons = build_details_keyboard(game, game.get("downloads", []))

            await query.edit_message_text(
                text=details_text,
                reply_markup=buttons,
                parse_mode=constants.ParseMode.HTML,
                disable_web_page_preview=False,
            )
        except (IndexError, ValueError) as e:
            logger.error(f"Error viewing game: {e}")
            await query.edit_message_text(
                "⚠ Glitch in the matrix. Could not load game."
            )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Uncaught error: %s", context.error)


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN missing.")

    # High timeout settings
    request = HTTPXRequest(
        connection_pool_size=8,
        read_timeout=30.0,
        write_timeout=30.0,
        connect_timeout=30.0,
    )

    app = Application.builder().token(TOKEN).request(request).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_error_handler(error_handler)

    print("🤖 Bot is online (Fast Cache Mode + Full Info)...")
    app.run_polling()
