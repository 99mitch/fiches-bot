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
