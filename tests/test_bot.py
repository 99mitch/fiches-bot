import json

import pytest

import bot
from bot import (
    COLUMNS,
    DIGIT_SEARCH,
    CardFieldRejected,
    SCHEMA,
    TEXT_SEARCH,
    _apply_schema,
    _reject_if_card,
    _search_session,
    _validate_fields,
    format_fiche,
    init_db,
    insert_fiches,
    load_schema,
    parse_line,
    save_schema,
    search_fiches,
)
from generate_test_data import generate_rows


@pytest.fixture
def restore_schema():
    """Snapshot the live schema and put it back after a test mutates it."""
    saved = (bot.SCHEMA, bot.COLUMNS, bot.TEXT_SEARCH, bot.DIGIT_SEARCH, dict(bot._LABELS))
    yield
    (bot.SCHEMA, bot.COLUMNS, bot.TEXT_SEARCH, bot.DIGIT_SEARCH, bot._LABELS) = (
        saved[0], saved[1], saved[2], saved[3], saved[4]
    )


def make_row(**overrides) -> dict:
    row = {col: "" for col in COLUMNS}
    row.update(overrides)
    return row


def to_line(**overrides) -> str:
    row = make_row(**overrides)
    return ",".join(row[col] for col in COLUMNS)


# --- schéma ---------------------------------------------------------------


def test_schema_keys_match_columns():
    assert COLUMNS == [f["key"] for f in SCHEMA]


def test_schema_declares_searchable_fields():
    assert TEXT_SEARCH, "au moins un champ de recherche texte est attendu"
    assert set(TEXT_SEARCH + DIGIT_SEARCH) <= set(COLUMNS)


def test_load_schema_rejects_invalid_key(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"fields": [{"key": "drop table", "label": "X"}]}))
    with pytest.raises(ValueError, match="invalide"):
        load_schema(str(path))


def test_load_schema_rejects_duplicate_key(tmp_path):
    path = tmp_path / "dup.json"
    path.write_text(
        json.dumps({"fields": [{"key": "a", "label": "A"}, {"key": "a", "label": "A2"}]})
    )
    with pytest.raises(ValueError, match="dupliquée"):
        load_schema(str(path))


def test_load_schema_rejects_reserved_key(tmp_path):
    path = tmp_path / "res.json"
    path.write_text(json.dumps({"fields": [{"key": "id", "label": "Id"}]}))
    with pytest.raises(ValueError, match="réservée"):
        load_schema(str(path))


# --- parsing --------------------------------------------------------------


def test_parse_line_full():
    row = parse_line(to_line(fullname="Jean Dupont", city="Paris", email="jean@ex.com"))
    assert row["fullname"] == "Jean Dupont"
    assert row["city"] == "Paris"
    assert row["email"] == "jean@ex.com"


def test_parse_line_partial():
    row = parse_line("FR,particulier,standard,Paul Martin")
    assert row["fullname"] == "Paul Martin"
    assert row["email"] == ""
    assert list(row.keys()) == COLUMNS


def test_parse_line_strips_spaces():
    row = parse_line("  FR , particulier , standard , Alice Durand ")
    assert row["country"] == "FR"
    assert row["fullname"] == "Alice Durand"


def test_parse_line_all_columns_present():
    values = [f"v{i}" for i in range(len(COLUMNS))]
    row = parse_line(",".join(values))
    assert list(row.keys()) == COLUMNS
    assert list(row.values()) == values


# --- base de données ------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


def test_insert_and_search_by_name(db):
    insert_fiches([make_row(fullname="Jean Dupont", email="jean@ex.com")], db)
    results = search_fiches("Jean Dupont", db)
    assert len(results) == 1
    assert results[0]["fullname"] == "Jean Dupont"


def test_search_by_email(db):
    insert_fiches([make_row(fullname="Jean Dupont", email="jean@ex.com")], db)
    assert len(search_fiches("jean@ex.com", db)) == 1


def test_search_by_city(db):
    insert_fiches([make_row(fullname="Jean Dupont", city="Nantes")], db)
    assert len(search_fiches("Nantes", db)) == 1


def test_search_by_phone(db):
    insert_fiches([make_row(fullname="Jean Dupont", phone="0612345678")], db)
    assert len(search_fiches("0612345678", db)) == 1


def test_search_phone_with_spaces(db):
    insert_fiches([make_row(fullname="Jean Dupont", phone="06 29 16 23 41")], db)
    assert len(search_fiches("06 29 16 23 41", db)) == 1
    assert len(search_fiches("0629162341", db)) == 1


def test_search_case_insensitive(db):
    insert_fiches([make_row(fullname="Jean Dupont")], db)
    assert len(search_fiches("jean dupont", db)) == 1


def test_search_no_result(db):
    assert search_fiches("inexistant", db) == []


def test_search_empty_query(db):
    insert_fiches([make_row(fullname="Jean Dupont")], db)
    assert search_fiches("   ", db) == []


def test_insert_multiple_rows(db):
    insert_fiches(
        [
            make_row(fullname="Alice Martin", email="a@ex.com"),
            make_row(fullname="Bob Bernard", email="b@ex.com"),
        ],
        db,
    )
    assert len(search_fiches("a@ex.com", db)) == 1
    assert len(search_fiches("b@ex.com", db)) == 1


def test_search_multiword_no_cross_match(db):
    insert_fiches(
        [make_row(fullname="Jean Dupont", city="Paris"), make_row(fullname="Alice Martin", city="Lyon")],
        db,
    )
    # Aucune ligne ne porte à la fois "Dupont" et "Lyon".
    assert len(search_fiches("Dupont Lyon", db)) == 0


def test_init_db_adds_missing_columns(tmp_path):
    import sqlite3

    path = str(tmp_path / "legacy.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE fiches (id INTEGER PRIMARY KEY AUTOINCREMENT, fullname TEXT)")
    con.commit()
    con.close()

    init_db(path)

    con = sqlite3.connect(path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(fiches)")}
    con.close()
    assert set(COLUMNS) <= cols


# --- recherche en session -------------------------------------------------


def test_search_session_by_text():
    fiches = [make_row(fullname="Jean Dupont"), make_row(fullname="Alice Martin")]
    assert [i for i, _ in _search_session(fiches, "dupont")] == [0]


def test_search_session_by_digits():
    fiches = [make_row(fullname="Jean Dupont", phone="06 12 34 56 78")]
    assert len(_search_session(fiches, "0612345678")) == 1


def test_search_session_empty_query():
    assert _search_session([make_row(fullname="Jean Dupont")], "  ") == []


# --- formatage ------------------------------------------------------------


def test_format_fiche_full():
    row = make_row(fullname="Jean Dupont", city="Paris", email="jean@ex.com")
    result = format_fiche(row)
    assert "Nom complet : Jean Dupont" in result
    assert "Ville : Paris" in result
    assert "Email : jean@ex.com" in result


def test_format_fiche_skips_empty():
    result = format_fiche(make_row(fullname="Martin"))
    assert "Nom complet : Martin" in result
    assert "Email" not in result
    assert "Ville" not in result


def test_format_fiche_follows_schema_order():
    row = make_row(**{col: "x" for col in COLUMNS})
    lines = format_fiche(row).splitlines()
    assert len(lines) == len(COLUMNS)


# --- données de test ------------------------------------------------------


def test_generate_rows_covers_every_column():
    rows = generate_rows(30, seed=1)
    assert len(rows) == 30
    for row in rows:
        assert list(row.keys()) == COLUMNS


def test_generate_rows_is_reproducible():
    assert generate_rows(5, seed=42) == generate_rows(5, seed=42)


def test_generated_rows_are_searchable(db):
    rows = generate_rows(20, seed=7)
    insert_fiches(rows, db)
    target = rows[0]
    assert len(search_fiches(target["email"], db)) >= 1
    assert len(search_fiches(target["phone"], db)) >= 1


def test_generated_rows_survive_parse_line():
    row = generate_rows(1, seed=3)[0]
    line = ",".join(f'"{row[c]}"' for c in COLUMNS)
    assert parse_line(line)["fullname"] == row["fullname"]


def test_dob_year_matches_dob():
    for row in generate_rows(20, seed=11):
        assert row["dob"].endswith(row["dob_year"])


def test_generated_emails_are_ascii():
    for row in generate_rows(50, seed=13):
        assert row["email"].isascii(), row["email"]
        assert " " not in row["email"]


def test_generated_phones_use_plausible_prefixes():
    for row in generate_rows(50, seed=17):
        assert row["phone"][:2] not in {"08", "09"}, row["phone"]


def test_generated_created_at_seconds_vary():
    seconds = {row["created_at"][-2:] for row in generate_rows(40, seed=19)}
    assert len(seconds) > 1


# --- édition de schéma à chaud ------------------------------------------


def test_apply_schema_swaps_globals(restore_schema):
    _apply_schema(SCHEMA + [{"key": "societe", "emoji": "🏢", "label": "Société", "search": "text"}])
    assert "societe" in bot.COLUMNS
    assert "societe" in bot.TEXT_SEARCH
    assert bot._LABELS["societe"] == "🏢 Société"


def test_apply_schema_remove_field(restore_schema):
    _apply_schema([f for f in SCHEMA if f["key"] != "city"])
    assert "city" not in bot.COLUMNS
    assert "city" not in bot.TEXT_SEARCH


def test_apply_schema_rejects_empty(restore_schema):
    with pytest.raises(ValueError):
        _apply_schema([])


def test_save_schema_round_trip(tmp_path):
    path = tmp_path / "s.json"
    fields = [{"key": "societe", "emoji": "🏢", "label": "Société", "search": "text"}]
    save_schema(fields, str(path))
    assert load_schema(str(path)) == fields


def test_save_schema_is_atomic(tmp_path):
    path = tmp_path / "s.json"
    save_schema([{"key": "a", "label": "A"}], str(path))
    assert not (tmp_path / "s.json.tmp").exists()


@pytest.mark.parametrize("key", ["cvv", "CVV", "cvc2", "pan", "card_number", "cardnumber", "cc"])
def test_reject_card_keys(key):
    with pytest.raises(CardFieldRejected):
        _reject_if_card(key)


def test_reject_card_by_label():
    with pytest.raises(CardFieldRejected):
        _reject_if_card("secure", "Numéro de carte bancaire")


@pytest.mark.parametrize("key", ["fullname", "email", "societe", "reference", "numero_commande"])
def test_allow_non_card_keys(key):
    _reject_if_card(key)  # ne lève pas


def test_validate_rejects_card_field():
    with pytest.raises(CardFieldRejected):
        _validate_fields([{"key": "cvv", "label": "CVV"}])


def test_added_field_becomes_searchable(restore_schema, db):
    _apply_schema(SCHEMA + [{"key": "societe", "emoji": "🏢", "label": "Société", "search": "text"}])
    init_db(db)  # applique ALTER TABLE ADD COLUMN
    insert_fiches([make_row(societe="Acme SARL")], db)
    assert len(search_fiches("Acme", db)) == 1


def test_search_treats_wildcards_literally(db):
    insert_fiches(
        [make_row(fullname="Jean Dupont"), make_row(fullname="%")],
        db,
    )
    # "%" ne doit pas se comporter comme un joker et tout ramener.
    results = search_fiches("%", db)
    assert [r["fullname"] for r in results] == ["%"]
