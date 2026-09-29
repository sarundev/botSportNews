import html
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

# .env និង data.json ស្ថិតនៅក្នុង folder របស់ bot នីមួយៗ
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
BOT_TITLE = os.getenv("BOT_TITLE", "SB24 – ព័ត៌មានកីឡា")
DATA_FILE = BASE_DIR / "data.json"

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(BASE_DIR.name)


# ---------- ខ្មែរ: លេខ និងកាលបរិច្ឆេទ ----------
TO_KHMER = str.maketrans("0123456789", "០១២៣៤៥៦៧៨៩")
KHMER_MONTHS = ["មករា", "កុម្ភៈ", "មីនា", "មេសា", "ឧសភា", "មិថុនា",
                "កក្កដា", "សីហា", "កញ្ញា", "តុលា", "វិច្ឆិកា", "ធ្នូ"]


def kh(value) -> str:
    return str(value).translate(TO_KHMER)


def kh_time(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return kh(f"ថ្ងៃទី {d.day} ខែ{KHMER_MONTHS[d.month - 1]} ម៉ោង {d:%H:%M}")


def esc(text) -> str:
    return html.escape(str(text))


# ---------- ប្រភេទកីឡា ----------
# អ្នកគ្រប់គ្រងអាចប្រើឈ្មោះកីឡាផ្សេងទៀតបាន — វានឹងប្រើរូប 🏅
SPORT_ICONS = {
    "បាល់ទាត់": "⚽",
    "ប្រដាល់": "🥊",
    "បាល់បោះ": "🏀",
    "បាល់ទះ": "🏐",
    "វាយសី": "🏸",
    "តេនីស": "🎾",
    "ហែលទឹក": "🏊",
    "រត់ប្រណាំង": "🏃",
    "ជិះកង់": "🚴",
    "អ៊ីស្ពត": "🎮",
}


def sport_label(sport: str) -> str:
    return f"{SPORT_ICONS.get(sport, '🏅')} {sport}"


# ---------- ទិន្នន័យ ----------
def load_data() -> dict:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {"next_id": 1, "posts": [], "subscribers": []}


def save_data(data: dict) -> None:
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def find_post(data: dict, post_id: int):
    return next((p for p in data["posts"] if p["id"] == post_id), None)


def sports_with_posts(data: dict) -> list:
    known = [s for s in SPORT_ICONS if any(p["sport"] == s for p in data["posts"])]
    others = sorted({p["sport"] for p in data["posts"]} - set(SPORT_ICONS))
    return known + others


# ---------- ប៊ូតុង ----------
BTN_LATEST = "📰 ព័ត៌មានថ្មីៗ"
BTN_SPORTS = "🏅 តាមប្រភេទកីឡា"
BTN_SUB = "🔔 បើកដំណឹង"
BTN_UNSUB = "🔕 បិទដំណឹង"
BTN_HELP = "ℹ️ ជំនួយ"
BTN_BACK = "⬅️ ត្រឡប់ទៅម៉ឺនុយដើម"


def main_menu(subscribed: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(BTN_LATEST, callback_data="latest")],
        [InlineKeyboardButton(BTN_SPORTS, callback_data="sports"),
         InlineKeyboardButton(BTN_UNSUB if subscribed else BTN_SUB, callback_data="sub")],
        [InlineKeyboardButton(BTN_HELP, callback_data="help")],
    ])


def back_button() -> list:
    return [InlineKeyboardButton(BTN_BACK, callback_data="menu")]


def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([back_button()])


def post_buttons(posts: list, extra_rows: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"{SPORT_ICONS.get(p['sport'], '🏅')} {p['title']}",
                                  callback_data=f"post:{p['id']}")] for p in posts]
    return InlineKeyboardMarkup(rows + extra_rows)


# ---------- អត្ថបទ ----------
def welcome_text() -> str:
    return (
        f"🏆 <b>{esc(BOT_TITLE)}</b>\n\n"
        "ព័ត៌មានកីឡាថ្មីៗ ពីក្នុង និងក្រៅប្រទេស ដោយផ្ទាល់នៅក្នុងតេឡេក្រាម។\n\n"
        f"<b>{BTN_LATEST}</b> — អានព័ត៌មានកីឡាចុងក្រោយ។\n"
        f"<b>{BTN_SPORTS}</b> — ជ្រើសរើសកីឡាដែលអ្នកចូលចិត្ត។\n"
        f"<b>{BTN_SUB}</b> — ទទួលព័ត៌មានថ្មីដោយស្វ័យប្រវត្តិ។\n\n"
        "👇 សូមជ្រើសរើសជម្រើសខាងក្រោម។"
    )


HELP_TEXT = (
    f"<b>{BTN_HELP}</b>\n\n"
    f"• <b>{BTN_LATEST}</b> — ព័ត៌មាន ១០ ចុងក្រោយ។ ចុចលើចំណងជើង ដើម្បីអាន។\n"
    f"• <b>{BTN_SPORTS}</b> — ⚽ បាល់ទាត់ 🥊 ប្រដាល់ 🏀 បាល់បោះ 🏐 បាល់ទះ និងកីឡាផ្សេងៗទៀត។\n"
    f"• <b>{BTN_SUB}</b> — ពេលមានព័ត៌មានថ្មី bot នឹងផ្ញើមកអ្នកភ្លាមៗ។ ចុចម្តងទៀត ដើម្បីបិទដំណឹង។\n\n"
    "<b>ពាក្យបញ្ជា៖</b>\n"
    "/start — បើកម៉ឺនុយដើម\n"
    "/help — បង្ហាញជំនួយ"
)


def post_text(p: dict) -> str:
    return (f"📰 <b>{esc(p['title'])}</b>\n"
            f"{sport_label(esc(p['sport']))} · 🕒 {kh_time(p['time'])}\n\n"
            f"{esc(p['body'])}")


# ---------- សម្រាប់អ្នកប្រើប្រាស់ ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    subscribed = update.effective_user.id in load_data()["subscribers"]
    await update.message.reply_text(welcome_text(), parse_mode=ParseMode.HTML,
                                    reply_markup=main_menu(subscribed))


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML, reply_markup=back_menu())


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    data = load_data()
    action = q.data
    uid = q.from_user.id

    async def show(text: str, markup: InlineKeyboardMarkup = None) -> None:
        try:
            await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup or back_menu())
        except BadRequest as e:
            if "not modified" not in str(e):
                raise

    if action == "sub":
        if uid in data["subscribers"]:
            data["subscribers"].remove(uid)
            note = "🔕 បានបិទដំណឹងហើយ។"
        else:
            data["subscribers"].append(uid)
            note = "🔔 បានបើកដំណឹងហើយ! អ្នកនឹងទទួលព័ត៌មានកីឡាថ្មីភ្លាមៗ។"
        save_data(data)
        await q.answer(note, show_alert=True)
        await show(welcome_text(), main_menu(uid in data["subscribers"]))
        return

    await q.answer()

    if action == "menu":
        await show(welcome_text(), main_menu(uid in data["subscribers"]))

    elif action == "latest":
        posts = sorted(data["posts"], key=lambda p: p["time"], reverse=True)[:10]
        if not posts:
            await show(f"<b>{BTN_LATEST}</b>\n\n📭 មិនទាន់មានព័ត៌មាននៅឡើយទេ។")
        else:
            await show(f"<b>{BTN_LATEST}</b>\n\n👇 ចុចលើចំណងជើង ដើម្បីអាន។",
                       post_buttons(posts, [back_button()]))

    elif action == "sports":
        names = sports_with_posts(data)
        if not names:
            await show(f"<b>{BTN_SPORTS}</b>\n\n📭 មិនទាន់មានព័ត៌មាននៅឡើយទេ។")
        else:
            buttons = [InlineKeyboardButton(sport_label(n), callback_data=f"sport:{i}") for i, n in enumerate(names)]
            rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]  # ២ ប៊ូតុងក្នុងមួយជួរ
            await show(f"<b>{BTN_SPORTS}</b>\n\n👇 សូមជ្រើសរើសកីឡា។", InlineKeyboardMarkup(rows + [back_button()]))

    elif action.startswith("sport:"):
        names = sports_with_posts(data)
        idx = int(action.split(":")[1])
        if idx >= len(names):
            await show(welcome_text(), main_menu(uid in data["subscribers"]))
            return
        posts = sorted((p for p in data["posts"] if p["sport"] == names[idx]),
                       key=lambda p: p["time"], reverse=True)[:10]
        back = [InlineKeyboardButton(f"⬅️ {BTN_SPORTS}", callback_data="sports")]
        await show(f"<b>{esc(sport_label(names[idx]))}</b>\n\n👇 ចុចលើចំណងជើង ដើម្បីអាន។",
                   post_buttons(posts, [back, back_button()]))

    elif action.startswith("post:"):
        p = find_post(data, int(action.split(":")[1]))
        if not p:
            await show("📭 ព័ត៌មាននេះត្រូវបានលុបហើយ។")
            return
        await show(post_text(p), InlineKeyboardMarkup([
            [InlineKeyboardButton(f"⬅️ {BTN_LATEST}", callback_data="latest")], back_button()]))

    elif action == "help":
        await show(HELP_TEXT)


# ---------- សម្រាប់អ្នកគ្រប់គ្រង ----------
ADMIN_HELP = (
    "🛠 <b>ពាក្យបញ្ជាអ្នកគ្រប់គ្រង</b>\n\n"
    "/post កីឡា | ចំណងជើង | អត្ថបទ\n"
    "— ផ្សព្វផ្សាយព័ត៌មានថ្មី ហើយផ្ញើទៅអ្នកដែលបើកដំណឹងទាំងអស់\n"
    "ឧទាហរណ៍៖ /post ប្រដាល់ | កីឡាករខ្មែរឈ្នះខ្សែក្រវាត់ | អត្ថបទព័ត៌មាន...\n\n"
    f"កីឡាដែលមានរូបស្រាប់៖ {'  '.join(sport_label(s) for s in SPORT_ICONS)}\n\n"
    "/posts — បង្ហាញព័ត៌មានទាំងអស់ និងលេខសម្គាល់\n\n"
    "/delpost លេខសម្គាល់ — លុបព័ត៌មាន\n\n"
    "/stats — ចំនួនអ្នកបើកដំណឹង និងព័ត៌មាន"
)


def is_admin(update: Update) -> bool:
    return update.effective_user.id in ADMIN_IDS


async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_admin(update):
        await update.message.reply_text(ADMIN_HELP, parse_mode=ParseMode.HTML)


async def add_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    parts = update.message.text.split(maxsplit=1)
    try:
        sport, title, body = [s.strip() for s in parts[1].split("|", 2)]
        if not (sport and title and body):
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("របៀបប្រើ៖\n/post កីឡា | ចំណងជើង | អត្ថបទ")
        return
    data = load_data()
    p = {"id": data["next_id"], "sport": sport, "title": title, "body": body,
         "time": datetime.now().isoformat(timespec="minutes")}
    data["posts"].append(p)
    data["next_id"] += 1

    sent, gone = 0, []
    markup = InlineKeyboardMarkup([[InlineKeyboardButton(BTN_LATEST, callback_data="latest")]])
    for uid in data["subscribers"]:
        try:
            await context.bot.send_message(uid, f"🆕 <b>ព័ត៌មានកីឡាថ្មី</b>\n\n{post_text(p)}",
                                           parse_mode=ParseMode.HTML, reply_markup=markup)
            sent += 1
        except Forbidden:
            gone.append(uid)  # អ្នកប្រើបានបិទ bot
        except Exception as e:
            log.warning("Could not send to %s: %s", uid, e)
    data["subscribers"] = [u for u in data["subscribers"] if u not in gone]
    save_data(data)
    await update.message.reply_text(f"✅ បានផ្សព្វផ្សាយព័ត៌មាន លេខ {p['id']} ទៅអ្នកបើកដំណឹង {kh(sent)} នាក់។")


async def list_posts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    posts = sorted(load_data()["posts"], key=lambda p: p["time"], reverse=True)
    lines = [f"លេខ {p['id']} [{sport_label(p['sport'])}] {p['title']} — {kh_time(p['time'])}" for p in posts[:30]]
    await update.message.reply_text("\n".join(lines) or "📭 មិនទាន់មានព័ត៌មាននៅឡើយទេ។")


async def delete_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    data = load_data()
    try:
        p = find_post(data, int(context.args[0]))
    except (IndexError, ValueError):
        p = None
    if not p:
        await update.message.reply_text("របៀបប្រើ៖ /delpost លេខសម្គាល់")
        return
    data["posts"].remove(p)
    save_data(data)
    await update.message.reply_text(f"🗑 បានលុបព័ត៌មាន លេខ {p['id']}។")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    data = load_data()
    await update.message.reply_text(
        f"📊 អ្នកបើកដំណឹង៖ {kh(len(data['subscribers']))} នាក់\n📰 ព័ត៌មាន៖ {kh(len(data['posts']))}")


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # លេខសម្គាល់ជាលេខអារ៉ាប់ ដើម្បីងាយចម្លងទៅដាក់ក្នុង .env
    await update.message.reply_text(f"🆔 លេខសម្គាល់តេឡេក្រាមរបស់អ្នក៖ {update.effective_user.id}")


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("start", "បើកម៉ឺនុយដើម"),
        BotCommand("help", "បង្ហាញជំនួយ"),
    ])


# ---------- ចាប់ផ្តើម ----------
def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit(f"BOT_TOKEN missing – copy {BASE_DIR.name}/.env.example to .env and add your token")
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("myid", my_id))
    app.add_handler(CommandHandler("admin", admin_help))
    app.add_handler(CommandHandler("post", add_post))
    app.add_handler(CommandHandler("posts", list_posts))
    app.add_handler(CommandHandler("delpost", delete_post))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(on_button))

    log.info("%s is running…", BOT_TITLE)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
