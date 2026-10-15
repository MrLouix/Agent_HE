"""Stockage des entrées d'usage et de la liste d'exclusion personnelle (SQLite)."""

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from agent_he.models import EntreeUsage, ExclusionPerso

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
    id TEXT PRIMARY KEY,
    horodatage TEXT NOT NULL,
    recette_ref TEXT,
    huiles TEXT NOT NULL,
    contenu TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exclusion_perso (
    he_id TEXT PRIMARY KEY,
    contenu TEXT NOT NULL
);
"""


class ErreurJournal(ValueError):
    pass


class Journal:
    def __init__(self, connexion: sqlite3.Connection) -> None:
        self._db = connexion
        self._db.executescript(SCHEMA)

    # --- Entrées d'usage --------------------------------------------------------------

    def ajouter(self, entree: EntreeUsage, huiles: Iterable[str] = ()) -> UUID:
        """Ajoute une entrée. `huiles` : identifiants des HE de la recette de référence."""
        he_ids = (
            sorted({d.he_id for d in entree.melange_libre})
            if entree.melange_libre is not None
            else sorted(set(huiles))
        )
        if not he_ids:
            raise ErreurJournal("une entrée doit indiquer les HE utilisées")
        self._db.execute(
            "INSERT INTO usage VALUES (?, ?, ?, ?, ?)",
            (
                str(entree.id),
                entree.horodatage.isoformat(),
                entree.recette_ref,
                json.dumps(he_ids),
                entree.model_dump_json(),
            ),
        )
        self._db.commit()
        return entree.id

    def obtenir(self, entree_id: UUID) -> EntreeUsage:
        ligne = self._db.execute(
            "SELECT contenu FROM usage WHERE id = ?", (str(entree_id),)
        ).fetchone()
        if ligne is None:
            raise ErreurJournal(f"entrée introuvable : {entree_id}")
        return EntreeUsage.model_validate_json(ligne["contenu"])

    def huiles(self, entree_id: UUID) -> list[str]:
        ligne = self._db.execute(
            "SELECT huiles FROM usage WHERE id = ?", (str(entree_id),)
        ).fetchone()
        if ligne is None:
            raise ErreurJournal(f"entrée introuvable : {entree_id}")
        return list(json.loads(ligne["huiles"]))

    def modifier(self, entree_id: UUID, **changements: Any) -> EntreeUsage:
        """Modifie une entrée (ex. réaction apparue le lendemain) ; revalide le modèle."""
        if {"id", "melange_libre", "recette_ref"} & changements.keys():
            raise ErreurJournal("la recette et l'identifiant d'une entrée ne se modifient pas")
        actuelle = self.obtenir(entree_id)
        nouvelle = EntreeUsage.model_validate({**actuelle.model_dump(), **changements})
        self._db.execute(
            "UPDATE usage SET horodatage = ?, contenu = ? WHERE id = ?",
            (nouvelle.horodatage.isoformat(), nouvelle.model_dump_json(), str(entree_id)),
        )
        self._db.commit()
        return nouvelle

    def supprimer(self, entree_id: UUID) -> None:
        self._db.execute("DELETE FROM usage WHERE id = ?", (str(entree_id),))
        self._db.commit()

    def lister(
        self,
        recette_ref: str | None = None,
        he_id: str | None = None,
        depuis: datetime | None = None,
    ) -> list[tuple[EntreeUsage, list[str]]]:
        """Entrées (avec leurs HE), de la plus récente à la plus ancienne."""
        lignes = self._db.execute(
            "SELECT contenu, huiles FROM usage ORDER BY horodatage DESC"
        ).fetchall()
        resultat: list[tuple[EntreeUsage, list[str]]] = []
        for ligne in lignes:
            entree = EntreeUsage.model_validate_json(ligne["contenu"])
            huiles = list(json.loads(ligne["huiles"]))
            if recette_ref is not None and entree.recette_ref != recette_ref:
                continue
            if he_id is not None and he_id not in huiles:
                continue
            if depuis is not None and entree.horodatage < depuis:
                continue
            resultat.append((entree, huiles))
        return resultat

    # --- Exclusions personnelles (toujours sur confirmation) --------------------------

    def confirmer_exclusion(self, exclusion: ExclusionPerso) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO exclusion_perso VALUES (?, ?)",
            (exclusion.he_id, exclusion.model_dump_json()),
        )
        self._db.commit()

    def retirer_exclusion(self, he_id: str) -> None:
        self._db.execute("DELETE FROM exclusion_perso WHERE he_id = ?", (he_id,))
        self._db.commit()

    def liste_exclusions(self) -> list[ExclusionPerso]:
        lignes = self._db.execute("SELECT contenu FROM exclusion_perso ORDER BY he_id").fetchall()
        return [ExclusionPerso.model_validate_json(ligne["contenu"]) for ligne in lignes]

    def exclusions(self) -> dict[str, str]:
        """`he_id` ⇒ motif, pour les contrôles de sécurité."""
        return {e.he_id: e.motif for e in self.liste_exclusions()}
