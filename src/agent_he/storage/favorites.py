"""Historique des réponses et favoris (SQLite)."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from agent_he.models import Demande, Fiche, Source

SCHEMA = """
CREATE TABLE IF NOT EXISTS historique (
    id TEXT PRIMARY KEY,
    horodatage TEXT NOT NULL,
    demande TEXT NOT NULL,
    fiche TEXT NOT NULL,
    sources TEXT NOT NULL,
    recette_ref TEXT
);
CREATE TABLE IF NOT EXISTS favori (
    id TEXT PRIMARY KEY,
    horodatage TEXT NOT NULL,
    nom TEXT NOT NULL,
    fiche TEXT NOT NULL,
    sources TEXT NOT NULL,
    recette_ref TEXT
);
"""


@dataclass(frozen=True)
class Enregistrement:
    id: str
    horodatage: datetime
    fiche: Fiche
    sources: list[Source]
    recette_ref: str | None
    demande: Demande | None = None
    nom: str = ""


def _sources_json(sources: list[Source]) -> str:
    return json.dumps([s.model_dump(mode="json") for s in sources], ensure_ascii=False)


def _sources(texte: str) -> list[Source]:
    return [Source.model_validate(s) for s in json.loads(texte)]


def reference(fiche: Fiche, recette_ref: str | None) -> str | None:
    """Référence stable d'une recette : identifiant du corpus, sinon nom de la recette."""
    if recette_ref:
        return recette_ref
    return fiche.recette.nom_recette if fiche.recette else None


class Historique:
    def __init__(self, connexion: sqlite3.Connection) -> None:
        self._db = connexion
        self._db.executescript(SCHEMA)

    def ajouter(
        self, demande: Demande, fiche: Fiche, sources: list[Source], recette_ref: str | None
    ) -> str:
        hid = uuid4().hex
        self._db.execute(
            "INSERT INTO historique VALUES (?, ?, ?, ?, ?, ?)",
            (
                hid,
                datetime.now(UTC).isoformat(),
                demande.model_dump_json(),
                fiche.model_dump_json(),
                _sources_json(sources),
                reference(fiche, recette_ref),
            ),
        )
        self._db.commit()
        return hid

    def lister(self, limite: int = 50) -> list[Enregistrement]:
        lignes = self._db.execute(
            "SELECT * FROM historique ORDER BY horodatage DESC LIMIT ?", (limite,)
        ).fetchall()
        return [
            Enregistrement(
                id=ligne["id"],
                horodatage=datetime.fromisoformat(ligne["horodatage"]),
                fiche=Fiche.model_validate_json(ligne["fiche"]),
                sources=_sources(ligne["sources"]),
                recette_ref=ligne["recette_ref"],
                demande=Demande.model_validate_json(ligne["demande"]),
            )
            for ligne in lignes
        ]


class Favoris:
    def __init__(self, connexion: sqlite3.Connection) -> None:
        self._db = connexion
        self._db.executescript(SCHEMA)

    def ajouter(self, fiche: Fiche, sources: list[Source], recette_ref: str | None) -> str:
        if fiche.recette is None:
            raise ValueError("seule une fiche avec recette peut être mise en favori")
        fid = uuid4().hex
        self._db.execute(
            "INSERT INTO favori VALUES (?, ?, ?, ?, ?, ?)",
            (
                fid,
                datetime.now(UTC).isoformat(),
                fiche.recette.nom_recette,
                fiche.model_dump_json(),
                _sources_json(sources),
                reference(fiche, recette_ref),
            ),
        )
        self._db.commit()
        return fid

    def supprimer(self, fid: str) -> None:
        self._db.execute("DELETE FROM favori WHERE id = ?", (fid,))
        self._db.commit()

    def lister(self) -> list[Enregistrement]:
        lignes = self._db.execute("SELECT * FROM favori ORDER BY horodatage DESC").fetchall()
        return [
            Enregistrement(
                id=ligne["id"],
                horodatage=datetime.fromisoformat(ligne["horodatage"]),
                fiche=Fiche.model_validate_json(ligne["fiche"]),
                sources=_sources(ligne["sources"]),
                recette_ref=ligne["recette_ref"],
                nom=ligne["nom"],
            )
            for ligne in lignes
        ]
