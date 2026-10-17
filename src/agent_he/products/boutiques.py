"""Configuration des boutiques (`data/boutiques.yaml`)."""

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, HttpUrl, TypeAdapter, model_validator

from agent_he.models import Modele, TexteNonVide


class Boutique(Modele):
    id: TexteNonVide
    nom: TexteNonVide
    url: HttpUrl
    acces: Literal["api", "flux", "scraping"]
    url_cgu: HttpUrl | None = None
    cgu_verifiees: bool = False
    cgu_verifiees_le: date | None = None
    delai_s: float = Field(default=5, ge=1)
    url_recherche: str | None = None
    motif_lien_produit: str | None = None
    extraction: Literal["jsonld"] = "jsonld"

    @model_validator(mode="after")
    def _verification_datee(self) -> "Boutique":
        if self.cgu_verifiees and self.cgu_verifiees_le is None:
            raise ValueError(f"{self.id} : indiquer la date de vérification des CGU")
        if self.url_recherche is not None and "{q}" not in self.url_recherche:
            raise ValueError(f"{self.id} : url_recherche doit contenir {{q}}")
        return self

    @property
    def active(self) -> bool:
        """Utilisable : CGU vérifiées et recherche configurée."""
        return self.cgu_verifiees and bool(self.url_recherche and self.motif_lien_produit)


_LISTE = TypeAdapter(list[Boutique])


def charger_boutiques(dossier_donnees: Path) -> list[Boutique]:
    chemin = dossier_donnees / "boutiques.yaml"
    return _LISTE.validate_python(yaml.safe_load(chemin.read_text(encoding="utf-8")) or [])
