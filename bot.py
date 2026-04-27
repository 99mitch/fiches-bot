import csv
import io
import os
import sqlite3

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
    cur = con.execute(
        "SELECT * FROM fiches WHERE nom COLLATE NOCASE = ? OR prenom COLLATE NOCASE = ? OR numero = ? OR email COLLATE NOCASE = ?",
        (query, query, query, query),
    )
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


_LABELS = {
    "nom": "Nom", "prenom": "Prénom", "numero": "Numéro",
    "date_naissance": "Date de naissance", "adresse": "Adresse",
    "code_postal": "Code postal", "ville": "Ville",
    "email": "Email", "iban": "IBAN", "bic": "BIC",
}


def format_fiche(row: dict) -> str:
    lines = [
        f"{label} : {row[col]}"
        for col, label in _LABELS.items()
        if row.get(col)
    ]
    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Bienvenue !\n\n"
        "Envoie un fichier .txt pour importer des fiches.\n"
        "Format : nom,prenom,numero,date_naissance,adresse,code_postal,ville,email,iban,bic\n\n"
        "Tape un nom, prenom, numero ou email pour rechercher une fiche."
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    doc = update.message.document
    if not doc.file_name.endswith(".txt"):
        await update.message.reply_text("Merci d'envoyer un fichier .txt")
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
    inserted = insert_fiches(rows)
    msg = f"{inserted} fiche(s) importee(s)."
    if skipped:
        msg += f"\n{skipped} ligne(s) ignoree(s)."
    await update.message.reply_text(msg)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.message.text.strip()
    results = search_fiches(query)
    if not results:
        await update.message.reply_text("Aucune fiche trouvee.")
        return
    parts = [f"--- Fiche #{i} ---\n{format_fiche(row)}" for i, row in enumerate(results, 1)]
    await update.message.reply_text("\n\n".join(parts))


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
