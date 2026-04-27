import csv
import io
import os
import sqlite3

from dotenv import load_dotenv

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
