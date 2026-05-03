import csv
import io
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    filters,
)

load_dotenv()

DB_DIR = os.getenv("DB_DIR", ".")


def chat_db(chat_id: int) -> str:
    path = os.path.join(DB_DIR, f"fiches_{chat_id}.db")
    init_db(path)
    return path
ADMIN_IDS = [int(i) for i in os.getenv("ADMIN_ID", "").split(",") if i.strip()]
COLUMNS = [
    "nom", "prenom", "numero", "date_naissance",
    "adresse", "code_postal", "ville", "email", "iban", "bic",
]


def parse_line(line: str) -> dict:
    reader = csv.reader(io.StringIO(line))
    fields = next(reader)
    return {col: (fields[i].strip() if i < len(fields) else "") for i, col in enumerate(COLUMNS)}


def init_db(db_path: str = "fiches.db") -> None:
    con = sqlite3.connect(db_path)
    con.execute(
        f"""CREATE TABLE IF NOT EXISTS fiches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {', '.join(f'{col} TEXT' for col in COLUMNS)}
        )"""
    )
    con.commit()
    con.close()


def insert_fiches(rows: list[dict], db_path: str = "fiches.db") -> int:
    con = sqlite3.connect(db_path)
    placeholders = ", ".join("?" for _ in COLUMNS)
    con.executemany(
        f"INSERT INTO fiches ({', '.join(COLUMNS)}) VALUES ({placeholders})",
        [[row[col] for col in COLUMNS] for row in rows],
    )
    con.commit()
    count = con.total_changes
    con.close()
    return count


def search_fiches(query: str, db_path: str = "fiches.db") -> list[dict]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    words = query.split()
    normalized = query.replace(" ", "")
    # Each word must match nom, prenom, or email (AND between words)
    per_word = "(nom COLLATE NOCASE = ? OR prenom COLLATE NOCASE = ? OR email COLLATE NOCASE = ?)"
    word_clause = " AND ".join(per_word for _ in words)
    word_params = [w for w in words for _ in range(3)]
    # Numero: compare full query (spaces stripped) against stored value (spaces stripped)
    sql = f"SELECT * FROM fiches WHERE ({word_clause}) OR REPLACE(numero, ' ', '') = ? LIMIT 10"
    cur = con.execute(sql, word_params + [normalized])
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


_LABELS = {
    "nom": "👤 Nom",
    "prenom": "👤 Prénom",
    "numero": "📞 Numéro",
    "date_naissance": "🎂 Date de naissance",
    "adresse": "🏠 Adresse",
    "code_postal": "📮 Code postal",
    "ville": "🏙️ Ville",
    "email": "📧 Email",
    "iban": "🏦 IBAN",
    "bic": "🏦 BIC",
}

_USER_COLORS = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "🟤", "🩷", "🩵", "🩶"]


def user_color(user_id: int) -> str:
    return _USER_COLORS[user_id % len(_USER_COLORS)]


def format_fiche(row: dict) -> str:
    lines = [
        f"{label} : {row[col]}"
        for col, label in _LABELS.items()
        if row.get(col)
    ]
    return "\n".join(lines)


def _viewer_keyboard(index: int, total: int) -> InlineKeyboardMarkup:
    row = []
    if index > 0:
        row.append(InlineKeyboardButton("◀ Précédente", callback_data="fv_prev"))
    if index < total - 1:
        row.append(InlineKeyboardButton("Suivante ▶", callback_data="fv_next"))
    return InlineKeyboardMarkup([row])


async def _do_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    user = update.effective_user
    color = user_color(user.id)
    mention = f"@{user.username}" if user.username else user.first_name
    db = chat_db(update.effective_chat.id)
    results = search_fiches(query, db)
    if not results:
        await update.message.reply_text("🔍 Aucune fiche trouvée.")
        return
    parts = [f"{color} Fiche #{i} — {mention}\n{format_fiche(row)}" for i, row in enumerate(results, 1)]
    await update.message.reply_text("\n\n".join(parts))
    if ADMIN_IDS:
        now = datetime.now(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H:%M:%S")
        notif = f"🔔 {mention} a sorti {len(results)} fiche(s) pour « {query} »\n🕐 {now}\n\n" + "\n\n".join(parts)
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(chat_id=admin_id, text=notif)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args:
        await _do_search(update, context, " ".join(context.args))
        return
    await update.message.reply_text(
        "👋 Bienvenue !\n\n"
        "📁 Envoie un fichier .txt pour importer des fiches.\n"
        "Format : nom,prenom,numero,date_naissance,adresse,code_postal,ville,email,iban,bic\n\n"
        "🔍 /fiche <nom|prénom|numéro|email> — rechercher une fiche\n"
        "📦 /bulk nom1 nom2 nom3 — rechercher plusieurs noms à la suite\n"
        "📋 Envoie un .txt avec la légende /fiches — parcourir les fiches avec ◀ ▶\n"
        "💬 Tape directement un texte pour rechercher."
    )


async def fiche(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("🔍 Usage : /fiche <nom|prénom|numéro|email>")
        return
    await _do_search(update, context, " ".join(context.args))


async def bulk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("📦 Usage : /bulk nom1 nom2 nom3 ...")
        return
    for name in context.args:
        try:
            await _do_search(update, context, name)
        except Exception as e:
            import sys
            print(f"bulk error for '{name}': {e}", file=sys.stderr)
            await update.message.reply_text(f"❌ Erreur pour « {name} ».")


async def fiches_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.document:
        await handle_fiches_viewer(update, context)
    else:
        await update.message.reply_text(
            "📋 Envoie un fichier .txt avec la légende /fiches pour parcourir les fiches une par une."
        )


async def handle_fiches_viewer(
    update: Update, context: ContextTypes.DEFAULT_TYPE, target_chat_id: int | None = None
) -> None:
    doc = update.message.document
    if not doc.file_name.endswith(".txt"):
        await update.message.reply_text("❌ Merci d'envoyer un fichier .txt")
        return
    tg_file = await doc.get_file()
    content = await tg_file.download_as_bytearray()
    text = content.decode("utf-8", errors="replace")
    fiches = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            fiches.append(parse_line(line))
        except Exception:
            pass
    if not fiches:
        await update.message.reply_text("❌ Aucune fiche dans ce fichier.")
        return
    total = len(fiches)
    fiche_text = f"📋 Fiche 1/{total}\n\n{format_fiche(fiches[0])}"
    keyboard = _viewer_keyboard(0, total)
    if target_chat_id:
        try:
            sent = await context.bot.send_message(
                chat_id=target_chat_id, text=fiche_text, reply_markup=keyboard
            )
            context.application.chat_data.setdefault(target_chat_id, {})["fv"] = {"fiches": fiches, "index": 0}
            await update.message.reply_text(f"✅ {total} fiche(s) envoyée(s) au groupe {target_chat_id}.")
        except Exception as e:
            await update.message.reply_text(f"❌ Impossible d'envoyer au groupe {target_chat_id} : {e}")
    else:
        context.chat_data["fv"] = {"fiches": fiches, "index": 0}
        await update.message.reply_text(fiche_text, reply_markup=keyboard)


async def handle_fiches_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    session = context.chat_data.get("fv")
    if not session:
        await query.edit_message_text("❌ Session expirée. Renvoie le fichier avec la légende /fiches.")
        return
    fiches = session["fiches"]
    total = len(fiches)
    index = session["index"]
    if query.data == "fv_prev":
        index = max(0, index - 1)
    elif query.data == "fv_next":
        index = min(total - 1, index + 1)
    session["index"] = index
    text = f"📋 Fiche {index + 1}/{total}\n\n{format_fiche(fiches[index])}"
    if len(text) > 4096:
        text = text[:4090] + "\n…"
    try:
        await query.edit_message_text(text, reply_markup=_viewer_keyboard(index, total))
    except Exception:
        await query.answer("⚠️ Erreur d'affichage.", show_alert=True)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    doc = update.message.document
    caption_raw = (update.message.caption or "").strip()
    caption_cmd = caption_raw.lower().split("@")[0].split()[0] if caption_raw else ""
    if caption_cmd == "/fiches":
        parts = caption_raw.split()
        target_chat_id = None
        if len(parts) >= 2:
            try:
                target_chat_id = int(parts[1])
            except ValueError:
                await update.message.reply_text("❌ Chat ID invalide. Exemple : /fiches -100123456789")
                return
        await handle_fiches_viewer(update, context, target_chat_id)
        return
    if not doc.file_name.endswith(".txt"):
        await update.message.reply_text("❌ Merci d'envoyer un fichier .txt")
        return
    tg_file = await doc.get_file()
    content = await tg_file.download_as_bytearray()
    text = content.decode("utf-8", errors="replace")
    rows = []
    skipped = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(parse_line(line))
        except Exception:
            skipped += 1
    try:
        inserted = insert_fiches(rows, chat_db(update.effective_chat.id))
    except Exception as e:
        import sys
        print(f"DB error: {e}", file=sys.stderr)
        await update.message.reply_text("❌ Erreur lors de l'import. Réessaie plus tard.")
        return
    msg = f"✅ {inserted} fiche(s) importée(s)."
    if skipped:
        msg += f"\n⚠️ {skipped} ligne(s) ignorée(s)."
    await update.message.reply_text(msg)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _do_search(update, context, update.message.text.strip())


def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN manquant dans .env")
    persistence = PicklePersistence(filepath="bot_persistence.pkl")
    app = Application.builder().token(token).persistence(persistence).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("fiche", fiche))
    app.add_handler(CommandHandler("bulk", bulk))
    app.add_handler(CommandHandler("fiches", fiches_cmd))
    app.add_handler(CallbackQueryHandler(handle_fiches_callback, pattern="^fv_(prev|next)$"))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()


if __name__ == "__main__":
    main()
