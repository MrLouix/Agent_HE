"""File de validation : recettes web candidates (priorité 1b) en attente de relecture.

Une candidate n'entre dans le corpus que par une décision explicite (`valider`), qui
l'exporte en JSON dans `data/recettes/`. Le journal d'usage n'intervient jamais ici
autrement qu'en information (spécification §11.4).
"""

import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from agent_he.kb.corpus import RecetteCorpus, ecrire_recette
from agent_he.models import Besoin, Confiance, Recette

StatutCandidate = Literal["en_attente", "validee", "rejetee"]


@dataclass(frozen=True)
class Candidate:
    id: str
    cree_le: datetime
    besoins: list[Besoin]
    confiance: Confiance
    recette: Recette
    statut: StatutCandidate
    motif: str | None = None
    recette_corpus: str | None = None


class ErreurValidation(ValueError):
    pass


def _empreinte(recette: Recette) -> str:
    canonique = json.dumps(recette.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonique.encode("utf-8")).hexdigest()


def identifiant_recette(nom: str) -> str:
    decompose = unicodedata.normalize("NFKD", nom.lower())
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", sans_accents).strip("-") or "recette"


class FileValidation:
    def __init__(self, connexion: sqlite3.Connection) -> None:
        self._db = connexion

    def ajouter(self, recette: Recette, besoins: list[Besoin], confiance: Confiance) -> str:
        """Ajoute une candidate (sans doublon) ; renvoie son identifiant."""
        empreinte = _empreinte(recette)
        existante = self._db.execute(
            "SELECT id FROM candidate WHERE empreinte = ?", (empreinte,)
        ).fetchone()
        if existante:
            return str(existante["id"])
        cid = f"C{empreinte[:8]}"
        self._db.execute(
            "INSERT INTO candidate (id, cree_le, empreinte, besoins, confiance, recette, statut)"
            " VALUES (?, ?, ?, ?, ?, ?, 'en_attente')",
            (
                cid,
                datetime.now(UTC).isoformat(),
                empreinte,
                json.dumps([str(b) for b in besoins]),
                str(confiance),
                recette.model_dump_json(),
            ),
        )
        self._db.commit()
        return cid

    def _depuis_ligne(self, ligne: sqlite3.Row) -> Candidate:
        return Candidate(
            id=ligne["id"],
            cree_le=datetime.fromisoformat(ligne["cree_le"]),
            besoins=[Besoin(b) for b in json.loads(ligne["besoins"])],
            confiance=Confiance(ligne["confiance"]),
            recette=Recette.model_validate_json(ligne["recette"]),
            statut=ligne["statut"],
            motif=ligne["motif"],
            recette_corpus=ligne["recette_corpus"],
        )

    def lister(self, statut: StatutCandidate | None = "en_attente") -> list[Candidate]:
        if statut is None:
            lignes = self._db.execute("SELECT * FROM candidate ORDER BY cree_le").fetchall()
        else:
            lignes = self._db.execute(
                "SELECT * FROM candidate WHERE statut = ? ORDER BY cree_le", (statut,)
            ).fetchall()
        return [self._depuis_ligne(ligne) for ligne in lignes]

    def obtenir(self, cid: str) -> Candidate:
        ligne = self._db.execute("SELECT * FROM candidate WHERE id = ?", (cid,)).fetchone()
        if ligne is None:
            raise ErreurValidation(f"candidate introuvable : {cid}")
        return self._depuis_ligne(ligne)

    def valider(
        self,
        cid: str,
        par: str,
        dossier_recettes: Path,
        le: date | None = None,
        besoins: list[Besoin] | None = None,
        identifiant: str | None = None,
    ) -> RecetteCorpus:
        """Exporte la candidate dans le corpus (décision explicite de relecture)."""
        candidate = self.obtenir(cid)
        if candidate.statut != "en_attente":
            raise ErreurValidation(f"{cid} : déjà {candidate.statut}")
        recette_corpus = RecetteCorpus(
            id=identifiant or identifiant_recette(candidate.recette.nom_recette),
            besoins=besoins or candidate.besoins,
            confiance=candidate.confiance,
            recette=candidate.recette,
            validee_par=par,
            validee_le=le or date.today(),
            origine=cid,
        )
        try:
            ecrire_recette(dossier_recettes, recette_corpus)
        except FileExistsError as exc:
            raise ErreurValidation(str(exc)) from exc
        self._db.execute(
            "UPDATE candidate SET statut = 'validee', traitee_le = ?, recette_corpus = ?"
            " WHERE id = ?",
            (datetime.now(UTC).isoformat(), recette_corpus.id, cid),
        )
        self._db.commit()
        return recette_corpus

    def rejeter(self, cid: str, motif: str) -> None:
        candidate = self.obtenir(cid)
        if candidate.statut != "en_attente":
            raise ErreurValidation(f"{cid} : déjà {candidate.statut}")
        if not motif.strip():
            raise ErreurValidation("un rejet exige un motif")
        self._db.execute(
            "UPDATE candidate SET statut = 'rejetee', motif = ?, traitee_le = ? WHERE id = ?",
            (motif, datetime.now(UTC).isoformat(), cid),
        )
        self._db.commit()
