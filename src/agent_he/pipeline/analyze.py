"""Analyse de la demande : catégories de besoin (spécification §5, étape 2).

Le repérage par mots-clés est fait par le code ; l'analyse LLM (phase 5) ne peut que
compléter les catégories, jamais modifier le profil de sécurité.
"""

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from agent_he.llm.base import LLM, ErreurLLM
from agent_he.llm.prompts import messages_analyse
from agent_he.models import Besoin
from agent_he.referentiel.huiles import simplifier

MOTS_BESOINS: dict[Besoin, tuple[str, ...]] = {
    Besoin.SOMMEIL: ("sommeil", "dormir", "endormissement", "insomnie", "nuit", "coucher"),
    Besoin.STRESS: ("stress", "anxiete", "angoisse", "detente", "relax", "calme", "apais"),
    Besoin.PEAU: ("peau", "bouton", "acne", "cicatri", "piqure", "irritation", "soin du visage"),
    Besoin.DIGESTION: ("digestion", "ballonnement", "ventre", "nausee", "transit"),
    Besoin.RESPIRATION: ("respir", "rhume", "nez bouche", "toux", "hiver", "degag", "sinus"),
    Besoin.DOULEURS: ("douleur", "muscle", "musculaire", "courbature", "articul", "dos", "crampe"),
    Besoin.CONCENTRATION: ("concentration", "memoire", "examen", "travail", "focus", "fatigue"),
    Besoin.AMBIANCE: ("ambiance", "odeur", "parfum", "assainir", "maison", "purifier"),
}


def categoriser(texte: str) -> list[Besoin]:
    """Catégories de besoin repérées dans le texte, dans l'ordre de l'énumération."""
    t = f" {simplifier(texte)} "
    return [b for b, mots in MOTS_BESOINS.items() if any(f" {m}" in t for m in mots)]


class AnalyseLLM(BaseModel):
    model_config = ConfigDict(extra="ignore")

    besoins: list[str] = Field(default_factory=list)
    mots_cles: list[str] = Field(default_factory=list)


@dataclass
class Analyse:
    besoins: list[Besoin]
    mots_cles: list[str] = field(default_factory=list)


def analyser(llm: LLM | None, besoin: str, texte_libre: str = "") -> Analyse:
    """Catégories du code, complétées par le LLM (qui ne peut qu'en ajouter de la liste)."""
    besoins = categoriser(f"{besoin} {texte_libre}")
    mots_cles: list[str] = []
    if llm is not None:
        try:
            reponse = llm.complete(messages_analyse(besoin, texte_libre), AnalyseLLM)
        except ErreurLLM:
            reponse = AnalyseLLM()
        valides = {str(b) for b in Besoin}
        for b in reponse.besoins:
            if b in valides and Besoin(b) not in besoins:
                besoins.append(Besoin(b))
        mots_cles = [m for m in reponse.mots_cles if m.strip()][:10]
    return Analyse(besoins=besoins, mots_cles=mots_cles)
