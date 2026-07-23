import csv
import io
import json
import os
import re
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

SCHEMA_PATH = os.getenv(
    "SCHEMA_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.json")
)

# Column names go straight into SQL identifiers, so keep them to a safe subset.
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_RESERVED = {"id"}

# Card-data field names are refused: storing a CVV/PAN is prohibited (PCI DSS)
# and there is no legitimate reason to add such a column. This blocks the
# obvious names — it is NOT a content check, since data can go in any column.
_BLOCKED_KEYS = {
    "cvv", "cvc", "cvv2", "cvc2", "cvn", "ccv", "cid",
    "pan", "card", "cardnumber", "card_number", "ccnumber", "cc_number",
    "cc", "ccnum", "track1", "track2", "track_data",
}
_BLOCKED_LABEL_RE = re.compile(
    r"cvv|cvc|\bpan\b|carte bancaire|numéro de carte|card number|card no",
    re.IGNORECASE,
)


class CardFieldRejected(ValueError):
    """Raised when someone tries to add a card-data field."""


def _reject_if_card(key: str, label: str = "") -> None:
    if key.replace("_", "").replace(" ", "") in {k.replace("_", "") for k in _BLOCKED_KEYS} \
            or key in _BLOCKED_KEYS or _BLOCKED_LABEL_RE.search(f"{key} {label}"):
        raise CardFieldRejected(
            "🚫 Champ de données de carte refusé (CVV / numéro de carte). "
            "Stocker ces données est interdit."
        )


def _validate_fields(fields: list[dict]) -> list[dict]:
    if not fields:
        raise ValueError("Le schéma ne contient aucun champ.")
    seen = set()
    for field in fields:
        key = field["key"]
        if not _KEY_RE.match(key):
            raise ValueError(f"Clé invalide : {key!r}")
        if key in _RESERVED:
            raise ValueError(f"Clé réservée : {key!r}")
        if key in seen:
            raise ValueError(f"Clé dupliquée : {key!r}")
        _reject_if_card(key, field.get("label", ""))
        seen.add(key)
    return fields


def load_schema(path: str = SCHEMA_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return _validate_fields(json.load(fh)["fields"])


def save_schema(fields: list[dict], path: str = SCHEMA_PATH) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"fields": fields}, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)  # atomic — never leaves a half-written schema


def _apply_schema(fields: list[dict]) -> None:
    """Validate then swap the live schema in — no process restart needed."""
    global SCHEMA, COLUMNS, TEXT_SEARCH, DIGIT_SEARCH, _LABELS
    _validate_fields(fields)
    SCHEMA = fields
    COLUMNS = [f["key"] for f in SCHEMA]
    TEXT_SEARCH = [f["key"] for f in SCHEMA if f.get("search") == "text"]
    DIGIT_SEARCH = [f["key"] for f in SCHEMA if f.get("search") == "digits"]
    _LABELS = _build_labels(SCHEMA)


def _build_labels(schema: list[dict]) -> dict:
    return {
        f["key"]: (f"{f['emoji']} {f['label']}".strip() if f.get("emoji") else f["label"])
        for f in schema
    }


SCHEMA = load_schema()
COLUMNS = [f["key"] for f in SCHEMA]
# Exact word match in the DB, substring match inside a loaded session.
TEXT_SEARCH = [f["key"] for f in SCHEMA if f.get("search") == "text"]
# Compared with spaces stripped on both sides (phone numbers, references…).
DIGIT_SEARCH = [f["key"] for f in SCHEMA if f.get("search") == "digits"]


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
    # A DB created with an older schema keeps its columns; add whatever is new
    # so an existing base survives a schema.json edit.
    existing = {r[1] for r in con.execute("PRAGMA table_info(fiches)")}
    for col in COLUMNS:
        if col not in existing:
            con.execute(f"ALTER TABLE fiches ADD COLUMN {col} TEXT")
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


def _like_escape(value: str) -> str:
    for ch in ("\\", "%", "_"):
        value = value.replace(ch, "\\" + ch)
    return value


def search_fiches(query: str, db_path: str = "fiches.db") -> list[dict]:
    words = query.split()
    if not words:
        return []
    clauses, params = [], []
    if TEXT_SEARCH:
        # Each word must appear in one of the text columns (AND between words),
        # so a combined field like "Jean Dupont" is reachable word by word.
        per_word = "(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in TEXT_SEARCH) + ")"
        clauses.append("(" + " AND ".join(per_word for _ in words) + ")")
        params += [f"%{_like_escape(w)}%" for w in words for _ in TEXT_SEARCH]
    if DIGIT_SEARCH:
        # Compare the full query (spaces stripped) against the stored value.
        normalized = query.replace(" ", "")
        clauses += [f"REPLACE({c}, ' ', '') = ?" for c in DIGIT_SEARCH]
        params += [normalized] * len(DIGIT_SEARCH)
    if not clauses:
        return []
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    sql = f"SELECT * FROM fiches WHERE {' OR '.join(clauses)} LIMIT 10"
    cur = con.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


_LABELS = _build_labels(SCHEMA)

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
    nav = []
    if index > 0:
        nav.append(InlineKeyboardButton("◀ Précédente", callback_data="fv_prev"))
    if index < total - 1:
        nav.append(InlineKeyboardButton("Suivante ▶", callback_data="fv_next"))
    delete_row = [InlineKeyboardButton("🗑️ Supprimer", callback_data="fv_del")]
    rows = []
    if nav:
        rows.append(nav)
    rows.append(delete_row)
    return InlineKeyboardMarkup(rows)


def _search_session(fiches: list[dict], query: str) -> list[tuple[int, dict]]:
    q = query.lower().strip()
    if not q:
        return []
    q_no_space = q.replace(" ", "")
    results = []
    for i, f in enumerate(fiches):
        if any((f.get(c) or "").replace(" ", "") == q_no_space for c in DIGIT_SEARCH):
            results.append((i, f))
            continue
        values = [(f.get(c) or "").lower() for c in TEXT_SEARCH]
        # Match a single field, or the fields joined in either order
        # ("dupont jean" and "jean dupont" both hit).
        if any(q in v for v in values) or q in " ".join(values) or q in " ".join(reversed(values)):
            results.append((i, f))
    return results


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
    searchable = " | ".join(TEXT_SEARCH + DIGIT_SEARCH) or "—"
    await update.message.reply_text(
        "👋 Bienvenue !\n\n"
        "📁 Envoie un fichier .txt pour importer des fiches.\n"
        f"Format : {','.join(COLUMNS)}\n\n"
        f"🔍 /fiche <{searchable}> — rechercher une fiche (base)\n"
        f"🔎 /search <{searchable}> — retrouver une fiche chargée dans ce groupe\n"
        "📦 /bulk terme1 terme2 terme3 — rechercher plusieurs termes à la suite\n"
        "🧩 /schema — afficher les champs configurés\n"
        "📋 Envoie un .txt avec la légende /fiches — parcourir les fiches avec ◀ ▶\n"
        "💬 Tape directement un texte pour rechercher."
    )


async def fiche(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        searchable = " | ".join(TEXT_SEARCH + DIGIT_SEARCH) or "—"
        await update.message.reply_text(f"🔍 Usage : /fiche <{searchable}>")
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


async def clearfiches(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = chat_db(update.effective_chat.id)
    con = sqlite3.connect(db)
    con.execute("DELETE FROM fiches")
    count = con.total_changes
    con.commit()
    con.close()
    await update.message.reply_text(f"🗑️ {count} fiche(s) supprimée(s) de ce groupe.")


def _is_admin(update: Update) -> bool:
    # No admin configured → nobody may edit the schema (fail closed).
    return bool(ADMIN_IDS) and update.effective_user.id in ADMIN_IDS


async def addfield_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await update.message.reply_text("🚫 Réservé aux administrateurs.")
        return
    args = list(context.args)
    search = None
    if args and args[0] in ("--text", "--digits"):
        search = args[0][2:]
        args = args[1:]
    if len(args) < 3:
        await update.message.reply_text(
            "➕ Usage : /addfield [--text|--digits] <clé> <emoji> <label>\n"
            "Ex : /addfield --text societe 🏢 Société"
        )
        return
    key, emoji, label = args[0].lower(), args[1], " ".join(args[2:])
    if key in COLUMNS:
        await update.message.reply_text(f"⚠️ Le champ « {key} » existe déjà.")
        return
    field = {"key": key, "emoji": emoji, "label": label}
    if search:
        field["search"] = search
    new_schema = SCHEMA + [field]
    try:
        _apply_schema(new_schema)
    except CardFieldRejected as e:
        await update.message.reply_text(str(e))
        return
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    save_schema(new_schema)
    await update.message.reply_text(
        f"✅ Champ ajouté : {_LABELS[key]} (`{key}`)\n"
        f"Il sera ajouté aux bases au prochain accès. Total : {len(COLUMNS)} champs."
    )


async def removefield_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await update.message.reply_text("🚫 Réservé aux administrateurs.")
        return
    if not context.args:
        await update.message.reply_text("➖ Usage : /removefield <clé>")
        return
    key = context.args[0].lower()
    if key not in COLUMNS:
        await update.message.reply_text(f"⚠️ Champ inconnu : « {key} ».")
        return
    new_schema = [f for f in SCHEMA if f["key"] != key]
    try:
        _apply_schema(new_schema)
    except ValueError as e:
        # e.g. removing the last field
        await update.message.reply_text(f"❌ Impossible : {e}")
        return
    save_schema(new_schema)
    await update.message.reply_text(
        f"✅ Champ « {key} » retiré du schéma.\n"
        "Les données déjà stockées dans les bases sont conservées mais ne sont "
        "plus affichées ; réajoute le champ pour les revoir."
    )


async def schema_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = []
    for field in SCHEMA:
        mark = {"text": " 🔍", "digits": " 🔢"}.get(field.get("search"), "")
        lines.append(f"{_LABELS[field['key']]} → `{field['key']}`{mark}")
    await update.message.reply_text(
        f"🧩 Schéma actuel ({len(SCHEMA)} champs)\n\n"
        + "\n".join(lines)
        + "\n\n🔍 = recherche texte · 🔢 = recherche numérique"
        + "\n\n➕ /addfield [--text|--digits] <clé> <emoji> <label>"
        + "\n➖ /removefield <clé>   (admins)"
    )


async def fiches_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.document:
        await handle_fiches_viewer(update, context)
    else:
        await update.message.reply_text(
            "📋 Envoie un fichier .txt avec la légende /fiches pour parcourir les fiches une par une."
        )


async def handle_fiches_viewer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_chat_id: int | None = None,
    allowed_users: list[int] | None = None,
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
    session = {"fiches": fiches, "index": 0, "allowed": allowed_users or []}
    if target_chat_id:
        try:
            await context.bot.send_message(
                chat_id=target_chat_id, text=fiche_text, reply_markup=keyboard
            )
            context.bot_data.setdefault("fv", {})[target_chat_id] = session
            await update.message.reply_text(f"✅ {total} fiche(s) envoyée(s) au groupe {target_chat_id}.")
        except Exception as e:
            await update.message.reply_text(f"❌ Impossible d'envoyer au groupe {target_chat_id} : {e}")
    else:
        context.chat_data["fv"] = session
        await update.message.reply_text(fiche_text, reply_markup=keyboard)


async def handle_fiches_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    session = context.chat_data.get("fv") or context.bot_data.get("fv", {}).get(chat_id)
    if session and "fv" not in context.chat_data:
        context.chat_data["fv"] = session
    if not session:
        await query.edit_message_text("❌ Session expirée. Renvoie le fichier avec la légende /fiches.")
        return
    allowed = session.get("allowed", [])
    if allowed and query.from_user.id not in allowed:
        await query.answer("🚫 Tu n'as pas accès à la navigation.", show_alert=True)
        return
    fiches = session["fiches"]
    total = len(fiches)
    index = session["index"]
    if query.data == "fv_del":
        fiches.pop(index)
        total -= 1
        if total == 0:
            session.clear()
            await query.edit_message_text("✅ Toutes les fiches ont été supprimées.")
            return
        index = min(index, total - 1)
    elif query.data == "fv_prev":
        index = max(0, index - 1)
    elif query.data == "fv_next":
        index = min(total - 1, index + 1)
    elif query.data.startswith("fv_goto_"):
        try:
            index = int(query.data[len("fv_goto_"):])
            index = max(0, min(index, total - 1))
        except ValueError:
            pass
    session["index"] = index
    session["fiches"] = fiches
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
        parts = caption_raw.split()[1:]  # drop "/fiches"
        target_chat_id = None
        allowed_users: list[int] = []
        for part in parts:
            try:
                val = int(part)
                if val < 0:
                    target_chat_id = val
                else:
                    allowed_users.append(val)
            except ValueError:
                await update.message.reply_text(f"❌ Valeur invalide : {part}")
                return
        await handle_fiches_viewer(update, context, target_chat_id, allowed_users)
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


async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        searchable = " ou ".join(TEXT_SEARCH + DIGIT_SEARCH) or "—"
        await update.message.reply_text(f"🔍 Usage : /search <{searchable}>")
        return
    query = " ".join(context.args)
    chat_id = update.effective_chat.id
    session = context.chat_data.get("fv") or context.bot_data.get("fv", {}).get(chat_id)
    if not session or not session.get("fiches"):
        await update.message.reply_text("❌ Aucune fiche chargée dans ce groupe. Envoie d'abord un fichier avec /fiches.")
        return
    results = _search_session(session["fiches"], query)
    if not results:
        await update.message.reply_text(f"🔍 Aucune fiche trouvée pour « {query} ».")
        return
    total = len(session["fiches"])
    for idx, row in results:
        text = f"📋 Fiche {idx + 1}/{total}\n\n{format_fiche(row)}"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📌 Aller à cette fiche", callback_data=f"fv_goto_{idx}")
        ]])
        await update.message.reply_text(text, reply_markup=keyboard)


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
    app.add_handler(CommandHandler("clearfiches", clearfiches))
    app.add_handler(CommandHandler("schema", schema_cmd))
    app.add_handler(CommandHandler("addfield", addfield_cmd))
    app.add_handler(CommandHandler("removefield", removefield_cmd))
    app.add_handler(CommandHandler("search", search_cmd))
    app.add_handler(CallbackQueryHandler(handle_fiches_callback, pattern="^fv_(prev|next|del|goto_\\d+)$"))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()


if __name__ == "__main__":
    main()
