import csv
import io
import os
import sqlite3
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

DB_PATH = "fiches.db"
ADMIN_IDS = [int(i) for i in os.getenv("ADMIN_ID", "").split(",") if i.strip()]
COLUMNS = [
    "nom", "prenom", "numero", "date_naissance",
    "adresse", "code_postal", "ville", "email", "iban", "bic",
]


def parse_line(line: str) -> dict:
    reader = csv.reader(io.StringIO(line))
    fields = next(reader)
    return {col: (fields[i].strip() if i < len(fields) else "") for i, col in enumerate(COLUMNS)}


def init_db(db_path: str = DB_PATH) -> None:
    con = sqlite3.connect(db_path)
    con.execute(
        f"""CREATE TABLE IF NOT EXISTS fiches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {', '.join(f'{col} TEXT' for col in COLUMNS)}
        )"""
    )
    con.commit()
    con.close()


def insert_fiches(rows: list[dict], db_path: str = DB_PATH) -> int:
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


def search_fiches(query: str, db_path: str = DB_PATH) -> list[dict]:
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


async def _do_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    user = update.effective_user
    color = user_color(user.id)
    mention = f"@{user.username}" if user.username else user.first_name
    results = search_fiches(query)
    if not results:
        await update.message.reply_text("🔍 Aucune fiche trouvée.")
        return
    parts = [f"{color} Fiche #{i} — {mention}\n{format_fiche(row)}" for i, row in enumerate(results, 1)]
    await update.message.reply_text("\n\n".join(parts))
    if ADMIN_IDS:
        now = datetime.now().strftime("%d/%m/%Y à %H:%M:%S")
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
        "🔍 Tape /start <nom|prénom|numéro|email> pour rechercher une fiche."
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    doc = update.message.document
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
        inserted = insert_fiches(rows)
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
    init_db()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN manquant dans .env")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()


if __name__ == "__main__":
    main()
