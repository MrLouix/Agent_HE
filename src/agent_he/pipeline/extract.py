"""Extraction structurée (LLM) : pages ⇒ recettes brutes, encore non normalisées."""

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_he.llm.base import LLM
from agent_he.llm.prompts import messages_extraction
from agent_he.search.base import Page


class _Brut(BaseModel):
    model_config = ConfigDict(extra="ignore")


class QuantiteBrute(_Brut):
    valeur: float
    unite: str


class HuileBrute(_Brut):
    nom: str
    nom_latin: str | None = None
    chemotype: str | None = None
    quantite: QuantiteBrute
    source: str


class PrecautionBrute(_Brut):
    texte: str
    source: str


class RecetteBrute(_Brut):
    nom_recette: str
    voie: str
    huiles: list[HuileBrute] = Field(default_factory=list)
    base_description: str = ""
    base_volume_ml: float | None = None
    usage: str = ""
    precautions: list[PrecautionBrute] = Field(default_factory=list)
    source: str


class IndicationBrute(_Brut):
    nom: str
    nom_latin: str | None = None
    type: Literal["plafond", "contre_indication"]
    voie: str | None = None
    valeur: float | None = None
    unite: str | None = None
    profil: str | None = None
    source: str


class Extraction(_Brut):
    recettes: list[RecetteBrute] = Field(default_factory=list)
    indications: list[IndicationBrute] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)


def extraire(llm: LLM, besoin: str, voies: Sequence[str], pages: Sequence[Page]) -> Extraction:
    """Une extraction par lot de pages ; aucune page ⇒ extraction vide sans appel."""
    if not pages:
        return Extraction()
    messages = messages_extraction(besoin, list(voies), [(p.url, p.texte) for p in pages])
    return llm.complete(messages, Extraction)
