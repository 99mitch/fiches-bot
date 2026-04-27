import pytest
from bot import parse_line, COLUMNS, init_db, insert_fiches, search_fiches


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
