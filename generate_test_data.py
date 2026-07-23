"""Génère des fiches de test conformes au schéma courant (schema.json).

Usage :
    python generate_test_data.py --count 50 --out test_fiches.txt
    python generate_test_data.py --count 50 --format csv --out test_fiches.csv

Les champs du schéma pour lesquels aucun générateur n'est défini sont laissés
vides — voir GENERATORS pour la liste des clés reconnues.
"""

import argparse
import csv
import random
import sys
import unicodedata
from datetime import date, datetime, timedelta

from bot import COLUMNS

_PRENOMS = [
    "Camille", "Lucas", "Léa", "Hugo", "Manon", "Nathan", "Chloé", "Louis",
    "Sarah", "Théo", "Emma", "Gabriel", "Inès", "Raphaël", "Jade", "Adam",
    "Louise", "Malo", "Anaïs", "Noé", "Zoé", "Ethan", "Alice", "Sacha",
]
_NOMS = [
    "Martin", "Bernard", "Dubois", "Thomas", "Robert", "Petit", "Durand",
    "Leroy", "Moreau", "Simon", "Laurent", "Lefebvre", "Michel", "Garcia",
    "David", "Bertrand", "Roux", "Vincent", "Fournier", "Morel", "Girard",
]
_VOIES = [
    "rue de la République", "avenue des Champs", "boulevard Victor Hugo",
    "rue des Lilas", "impasse du Moulin", "place de la Mairie",
    "chemin des Vignes", "allée des Peupliers", "rue Pasteur",
]
_VILLES = [
    ("Paris", "750"), ("Lyon", "690"), ("Marseille", "130"), ("Toulouse", "310"),
    ("Nantes", "440"), ("Bordeaux", "330"), ("Lille", "590"), ("Rennes", "350"),
    ("Strasbourg", "670"), ("Montpellier", "340"), ("Nice", "060"),
]
_DOMAINES = ["example.com", "example.org", "test.local", "mail.example"]
_PAYS = ["FR", "BE", "CH", "LU", "CA"]
_TYPES = ["particulier", "professionnel"]
_CATEGORIES = ["standard", "premium", "vip", "prospect"]
_INFOS = [
    "Client fidèle depuis 2021", "Préfère être contacté par email",
    "Ne pas appeler avant 10h", "Dossier en attente de validation",
    "Adresse de livraison différente", "", "", "",
]


def _slug(value: str) -> str:
    """« Zoé Le Roy » → « zoe.le.roy » (accents retirés, adresse email valide)."""
    decomposed = unicodedata.normalize("NFKD", value.lower())
    out = []
    for ch in decomposed:
        if unicodedata.combining(ch):
            continue
        if ch.isascii() and ch.isalnum():
            out.append(ch)
        elif ch in " -'":
            out.append(".")
    return "".join(out).strip(".")


def _build_person(rng: random.Random) -> dict:
    """Champs corrélés entre eux (nom ↔ email, ville ↔ code postal, dob ↔ année)."""
    prenom, nom = rng.choice(_PRENOMS), rng.choice(_NOMS)
    ville, prefixe = rng.choice(_VILLES)
    naissance = date(
        rng.randint(1955, 2005), rng.randint(1, 12), rng.randint(1, 28)
    )
    creation = datetime.now().replace(microsecond=0) - timedelta(
        days=rng.randint(0, 900), minutes=rng.randint(0, 1439), seconds=rng.randint(0, 59)
    )
    return {
        "country": rng.choice(_PAYS),
        "type": rng.choice(_TYPES),
        "category": rng.choice(_CATEGORIES),
        "fullname": f"{prenom} {nom}",
        "address": f"{rng.randint(1, 180)} {rng.choice(_VOIES)}",
        "zip": f"{prefixe}{rng.randint(1, 20):02d}",
        "city": ville,
        "email": f"{_slug(prenom)}.{_slug(nom)}{rng.randint(1, 99)}@{rng.choice(_DOMAINES)}",
        # 06/07 mobile, 01-05 fixe. On évite 08 (surtaxé) et 09 (VoIP).
        "phone": "0{} {}".format(
            rng.choice("6712345"),
            " ".join(f"{rng.randint(0, 99):02d}" for _ in range(4)),
        ),
        "dob": naissance.strftime("%d/%m/%Y"),
        "dob_year": str(naissance.year),
        "additional_infos": rng.choice(_INFOS),
        "created_at": creation.strftime("%Y-%m-%d %H:%M:%S"),
    }


def generate_rows(count: int, seed: int | None = None) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for _ in range(count):
        person = _build_person(rng)
        # Le schéma fait foi : tout champ inconnu du générateur reste vide.
        rows.append({col: person.get(col, "") for col in COLUMNS})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--count", type=int, default=50, help="nombre de fiches")
    parser.add_argument("-o", "--out", help="fichier de sortie (défaut : stdout)")
    parser.add_argument(
        "-f", "--format", choices=["txt", "csv"], default="txt",
        help="txt = une fiche par ligne (import bot), csv = avec en-tête",
    )
    parser.add_argument("--seed", type=int, help="graine pour un tirage reproductible")
    args = parser.parse_args()

    rows = generate_rows(args.count, args.seed)
    missing = [c for c in COLUMNS if not any(r[c] for r in rows)]

    stream = open(args.out, "w", newline="", encoding="utf-8") if args.out else sys.stdout
    try:
        writer = csv.writer(stream)
        if args.format == "csv":
            writer.writerow(COLUMNS)
        writer.writerows([[r[c] for c in COLUMNS] for r in rows])
    finally:
        if args.out:
            stream.close()

    if args.out:
        print(f"✅ {len(rows)} fiche(s) écrite(s) dans {args.out}", file=sys.stderr)
    if missing:
        print(f"⚠️ Champs laissés vides (aucun générateur) : {', '.join(missing)}", file=sys.stderr)


if __name__ == "__main__":
    main()
