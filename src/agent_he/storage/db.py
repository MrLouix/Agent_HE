"""Connexion SQLite et schéma (créé à la demande, idempotent)."""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidate (
    id TEXT PRIMARY KEY,
    cree_le TEXT NOT NULL,
    empreinte TEXT NOT NULL UNIQUE,
    besoins TEXT NOT NULL,
    confiance TEXT NOT NULL,
    recette TEXT NOT NULL,
    statut TEXT NOT NULL CHECK (statut IN ('en_attente', 'validee', 'rejetee')),
    motif TEXT,
    traitee_le TEXT,
    recette_corpus TEXT
);
"""


def connecter(chemin: Path | str) -> sqlite3.Connection:
    """Ouvre la base (créée si besoin) ; `":memory:"` pour les tests."""
    if isinstance(chemin, Path):
        chemin.parent.mkdir(parents=True, exist_ok=True)
    # Streamlit réexécute le script dans des threads différents : la connexion conservée
    # en session doit pouvoir y être utilisée (outil mono-utilisateur, accès séquentiels).
    connexion = sqlite3.connect(str(chemin), check_same_thread=False)
    connexion.row_factory = sqlite3.Row
    connexion.execute("PRAGMA foreign_keys = ON")
    connexion.executescript(SCHEMA)
    return connexion
