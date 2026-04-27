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
