# Fiches Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un bot Telegram Python qui importe des fiches CSV dans SQLite et les recherche par nom, prénom, numéro ou email.

**Architecture:** Fichier unique `bot.py` contenant les fonctions DB pures (testables) et les handlers Telegram. Les fonctions DB prennent `db_path` en paramètre pour faciliter les tests avec une base temporaire.

**Tech Stack:** Python 3.11+, python-telegram-bot 20+, python-dotenv, SQLite3, pytest

---

## File Structure

```
fiches-bot/
├── bot.py              # Tout le code : DB, parsing, handlers, main
├── tests/
│   └── test_bot.py     # Tests unitaires des fonctions pures
├── requirements.txt
├── .env                # BOT_TOKEN=xxx  (non commité)
├── .env.example        # BOT_TOKEN=your_token_here
└── .gitignore
```

---

### Task 1: Setup projet

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`

- [ ] **Step 1: Créer requirements.txt**

```
python-telegram-bot==20.7
python-dotenv==1.0.1
pytest==8.1.1
```

- [ ] **Step 2: Créer .env.example**

```
BOT_TOKEN=your_token_here
```

- [ ] **Step 3: Créer .gitignore**

```
.env
fiches.db
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 4: Installer les dépendances**

```bash
pip install -r requirements.txt
```

Expected: installation sans erreur.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .env.example .gitignore
git commit -m "chore: project setup"
```

---

### Task 2: Fonction parse_line

**Files:**
- Create: `bot.py` (squelette + `parse_line`)
- Create: `tests/test_bot.py`

- [ ] **Step 1: Créer le squelette de bot.py**

```python
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
```

- [ ] **Step 2: Créer tests/test_bot.py avec le test de parse_line**

```python
import pytest
from bot import parse_line, COLUMNS


def test_parse_line_full():
    line = "Dupont,Jean,0612345678,01/01/1990,12 rue de la Paix,75001,Paris,jean@example.com,FR76xxx,BNPA"
    row = parse_line(line)
    assert row["nom"] == "Dupont"
    assert row["prenom"] == "Jean"
    assert row["numero"] == "0612345678"
    assert row["email"] == "jean@example.com"
    assert row["bic"] == "BNPA"


def test_parse_line_partial():
    line = "Martin,Paul,0600000000"
    row = parse_line(line)
    assert row["nom"] == "Martin"
    assert row["prenom"] == "Paul"
    assert row["numero"] == "0600000000"
    assert row["email"] == ""
    assert row["iban"] == ""


def test_parse_line_strips_spaces():
    line = " Durand , Alice , 0699999999 "
    row = parse_line(line)
    assert row["nom"] == "Durand"
    assert row["prenom"] == "Alice"
    assert row["numero"] == "0699999999"


def test_parse_line_all_columns_present():
    line = "a,b,c,d,e,f,g,h,i,j"
    row = parse_line(line)
    assert list(row.keys()) == COLUMNS
    assert list(row.values()) == ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]
```

- [ ] **Step 3: Lancer les tests pour vérifier qu'ils passent**

```bash
pytest tests/test_bot.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add bot.py tests/test_bot.py
git commit -m "feat: add parse_line with tests"
```

---

### Task 3: Fonctions DB (init, insert, search)

**Files:**
- Modify: `bot.py` — ajouter `init_db`, `insert_fiches`, `search_fiches`
- Modify: `tests/test_bot.py` — ajouter tests DB

- [ ] **Step 1: Écrire les tests DB dans tests/test_bot.py**

Ajouter à la fin du fichier :

```python
import tempfile
import os
from bot import init_db, insert_fiches, search_fiches


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


def test_insert_and_search_by_nom(db):
    rows = [parse_line("Dupont,Jean,0612345678,,,,,jean@ex.com,,")]
    insert_fiches(rows, db)
    results = search_fiches("Dupont", db)
    assert len(results) == 1
    assert results[0]["nom"] == "Dupont"


def test_search_by_prenom(db):
    rows = [parse_line("Dupont,Jean,0612345678,,,,,jean@ex.com,,")]
    insert_fiches(rows, db)
    results = search_fiches("Jean", db)
    assert len(results) == 1


def test_search_by_numero(db):
    rows = [parse_line("Dupont,Jean,0612345678,,,,,jean@ex.com,,")]
    insert_fiches(rows, db)
    results = search_fiches("0612345678", db)
    assert len(results) == 1


def test_search_by_email(db):
    rows = [parse_line("Dupont,Jean,0612345678,,,,,jean@ex.com,,")]
    insert_fiches(rows, db)
    results = search_fiches("jean@ex.com", db)
    assert len(results) == 1


def test_search_case_insensitive(db):
    rows = [parse_line("Dupont,Jean,,,,,,,, ")]
    insert_fiches(rows, db)
    results = search_fiches("dupont", db)
    assert len(results) == 1


def test_search_no_result(db):
    results = search_fiches("inexistant", db)
    assert results == []


def test_insert_multiple_rows(db):
    rows = [
        parse_line("Martin,Alice,0600000001,,,,,a@ex.com,,"),
        parse_line("Bernard,Bob,0600000002,,,,,b@ex.com,,"),
    ]
    insert_fiches(rows, db)
    assert len(search_fiches("Martin", db)) == 1
    assert len(search_fiches("Bob", db)) == 1
```

- [ ] **Step 2: Lancer les tests pour confirmer qu'ils échouent**

```bash
pytest tests/test_bot.py -v
```

Expected: FAIL — `init_db`, `insert_fiches`, `search_fiches` not defined.

- [ ] **Step 3: Implémenter les fonctions DB dans bot.py**

Ajouter après `parse_line` :

```python
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
        "SELECT * FROM fiches WHERE nom = ? OR prenom = ? OR numero = ? OR email = ? COLLATE NOCASE",
        (query, query, query, query),
    )
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows
```

- [ ] **Step 4: Lancer les tests**

```bash
pytest tests/test_bot.py -v
```

Expected: tous les tests PASS.

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/test_bot.py
git commit -m "feat: add DB functions with tests"
```

---

### Task 4: Fonction format_fiche

**Files:**
- Modify: `bot.py` — ajouter `format_fiche`
- Modify: `tests/test_bot.py` — ajouter tests format

- [ ] **Step 1: Écrire les tests dans tests/test_bot.py**

Ajouter à la fin :

```python
from bot import format_fiche


def test_format_fiche_full():
    row = {
        "id": 1, "nom": "Dupont", "prenom": "Jean", "numero": "0612345678",
        "date_naissance": "01/01/1990", "adresse": "12 rue de la Paix",
        "code_postal": "75001", "ville": "Paris", "email": "jean@ex.com",
        "iban": "FR76xxx", "bic": "BNPA",
    }
    result = format_fiche(row)
    assert "Nom : Dupont" in result
    assert "Prénom : Jean" in result
    assert "Email : jean@ex.com" in result


def test_format_fiche_skips_empty():
    row = {col: "" for col in COLUMNS}
    row["id"] = 1
    row["nom"] = "Martin"
    result = format_fiche(row)
    assert "Nom : Martin" in result
    assert "Prénom" not in result
    assert "Email" not in result
```

- [ ] **Step 2: Lancer les tests pour confirmer l'échec**

```bash
pytest tests/test_bot.py::test_format_fiche_full tests/test_bot.py::test_format_fiche_skips_empty -v
```

Expected: FAIL — `format_fiche` not defined.

- [ ] **Step 3: Implémenter format_fiche dans bot.py**

Ajouter après `search_fiches` :

```python
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
```

- [ ] **Step 4: Lancer tous les tests**

```bash
pytest tests/test_bot.py -v
```

Expected: tous les tests PASS.

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/test_bot.py
git commit -m "feat: add format_fiche with tests"
```

---

### Task 5: Handlers Telegram et main

**Files:**
- Modify: `bot.py` — ajouter les imports Telegram, handlers, et `main()`

- [ ] **Step 1: Ajouter les imports Telegram en haut de bot.py**

Remplacer la section des imports par :

```python
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
```

- [ ] **Step 2: Ajouter les handlers à la fin de bot.py (avant un éventuel main)**

```python
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
```

- [ ] **Step 3: Lancer tous les tests pour vérifier aucune régression**

```bash
pytest tests/test_bot.py -v
```

Expected: tous les tests PASS.

- [ ] **Step 4: Créer le .env avec le vrai token**

```bash
echo "BOT_TOKEN=<ton_token_botfather>" > .env
```

- [ ] **Step 5: Lancer le bot et tester manuellement**

```bash
python bot.py
```

Expected: le bot démarre sans erreur (`Application started`).
Dans Telegram : envoyer `/start` → message de bienvenue.
Envoyer un fichier .txt avec 2-3 lignes → réponse "X fiches importées."
Taper un nom → résultat ou "Aucune fiche trouvée."

- [ ] **Step 6: Commit**

```bash
git add bot.py
git commit -m "feat: add telegram handlers and main"
```
