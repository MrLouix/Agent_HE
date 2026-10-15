"""Recettes validées du corpus (`data/recettes/*.json`)."""

from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from agent_he.models import Besoin, Confiance, Modele, Recette, TexteNonVide

IdRecette = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]*$")]


class RecetteCorpus(Modele):
    id: IdRecette
    statut: Literal["validee"] = "validee"
    besoins: list[Besoin] = Field(min_length=1)
    mots_cles: list[str] = Field(default_factory=list)
    confiance: Confiance
    recette: Recette
    validee_par: TexteNonVide
    validee_le: date
    origine: str | None = None
    """Identifiant de la candidate de la file de validation, le cas échéant."""

    def texte_index(self) -> str:
        """Texte indexé pour la recherche par similarité."""
        huiles = " ".join(h.nom for h in self.recette.huiles)
        return " ".join(
            [
                *[str(b) for b in self.besoins],
                *self.mots_cles,
                self.recette.nom_recette,
                self.recette.usage,
                huiles,
            ]
        )


def charger_corpus(dossier: Path) -> dict[str, RecetteCorpus]:
    corpus: dict[str, RecetteCorpus] = {}
    for chemin in sorted(dossier.glob("*.json")):
        recette = RecetteCorpus.model_validate_json(chemin.read_text(encoding="utf-8"))
        if recette.id != chemin.stem:
            raise ValueError(f"{chemin.name} : l'identifiant doit être « {chemin.stem} »")
        if recette.id in corpus:
            raise ValueError(f"recette en double : {recette.id}")
        corpus[recette.id] = recette
    return corpus


def ecrire_recette(dossier: Path, recette: RecetteCorpus) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"{recette.id}.json"
    if chemin.exists():
        raise FileExistsError(f"la recette {recette.id} existe déjà")
    chemin.write_text(recette.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return chemin
