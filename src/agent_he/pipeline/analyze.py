"""Analyse de la demande : catégories de besoin (spécification §5, étape 2).

Le repérage par mots-clés est fait par le code ; l'analyse LLM (phase 5) ne peut que
compléter les catégories, jamais modifier le profil de sécurité.
"""

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
