# Fiches Bot — Design Spec

**Date:** 2026-04-27

## Overview

Un bot Telegram en Python qui permet d'importer des fiches personnelles (fichier .txt CSV) dans une base SQLite et de les rechercher par nom, prénom, numéro de téléphone ou email.

## Stack

- **Langage:** Python 3.11+
- **Lib Telegram:** python-telegram-bot v20+ (async)
- **Base de données:** SQLite (fichier local `fiches.db`)
- **Config:** token bot dans un fichier `.env`
- **Architecture:** fichier unique `bot.py`

## Structure des fichiers

```
fiches-bot/
├── bot.py          # Tout le code : handlers, DB, parsing
├── fiches.db       # Créé automatiquement au premier lancement
├── .env            # BOT_TOKEN=xxx
└── requirements.txt
```

## Schéma de la base de données

Table `fiches` :

| Colonne         | Type | Notes                  |
|----------------|------|------------------------|
| id             | INTEGER PRIMARY KEY AUTOINCREMENT | |
| nom            | TEXT | Peut être vide         |
| prenom         | TEXT | Peut être vide         |
| numero         | TEXT | Peut être vide         |
| date_naissance | TEXT | Peut être vide         |
| adresse        | TEXT | Peut être vide         |
| code_postal    | TEXT | Peut être vide         |
| ville          | TEXT | Peut être vide         |
| email          | TEXT | Peut être vide         |
| iban           | TEXT | Peut être vide         |
| bic            | TEXT | Peut être vide         |

## Format du fichier d'import

- Fichier `.txt` envoyé comme document Telegram
- Séparateur : virgule `,`
- Ordre des colonnes fixe : `nom,prenom,numero,date_naissance,adresse,code_postal,ville,email,iban,bic`
- Les champs manquants sont acceptés (la ligne peut avoir moins de 10 champs)
- Pas de ligne d'en-tête (les données commencent dès la première ligne)
- Encoding attendu : UTF-8

## Comportements du bot

### `/start`
Répond avec un message d'accueil expliquant :
- Comment envoyer un fichier pour importer des fiches
- Comment chercher (taper un nom, prénom, numéro ou email)

### Upload d'un fichier `.txt`
1. Le bot télécharge le fichier
2. Parse chaque ligne comme CSV
3. Insère chaque ligne dans la table `fiches` (les champs manquants → chaîne vide)
4. Répond : "X fiches importées." (ou un message d'erreur si le fichier est invalide)

### Message texte (recherche)
1. Prend le texte brut envoyé par l'utilisateur
2. Cherche dans `nom`, `prenom`, `numero`, `email` avec `LIKE` insensible à la casse (`COLLATE NOCASE`)
3. Retourne toutes les fiches correspondantes, formatées lisiblement
4. Si aucun résultat : "Aucune fiche trouvée."

### Tout autre type de message
Ignoré (pas de réponse).

## Formatage des résultats

Chaque fiche retournée est affichée sous forme de bloc texte :

```
--- Fiche #1 ---
Nom : Dupont
Prénom : Jean
Numéro : 0612345678
Date de naissance : 01/01/1990
Adresse : 12 rue de la Paix
Code postal : 75001
Ville : Paris
Email : jean.dupont@example.com
IBAN : FR76...
BIC : BNPAFRPP
```

Les champs vides sont omis de l'affichage.

## Gestion des erreurs

- Fichier non `.txt` → message d'erreur explicite
- Ligne mal formée dans le fichier → ignorée, comptée séparément
- DB inaccessible → log stderr, message d'erreur à l'utilisateur

## Dépendances

```
python-telegram-bot==20.*
python-dotenv
```
