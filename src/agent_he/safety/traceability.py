"""Traçabilité (spécification §6, contrôle 4) : un élément non rattaché à une source est retiré.

Une HE est tracée si l'une de ses sources citées fait partie des sources récupérées et
que le texte de cette source mentionne l'HE (sous l'un de ses noms du référentiel) et la
valeur de sa quantité. Une précaution est tracée si son texte figure dans une source citée.
Le journal d'usage n'est jamais une source : seules les URL récupérées sont acceptées.
"""

import re
from dataclasses import dataclass, field

from agent_he.models import DoseHE, Precaution, Recette
from agent_he.referentiel.huiles import Referentiel, simplifier

_SEUIL_PRECAUTION = 0.8
# Les négations (« ne », « pas », « jamais ») ne sont pas des mots vides : elles inversent le sens.
_MOTS_VIDES = frozenset(
    [
        "a",
        "au",
        "aux",
        "avec",
        "ce",
        "ces",
        "d",
        "dans",
        "de",
        "des",
        "du",
        "en",
        "et",
        "l",
        "la",
        "le",
        "les",
        "ou",
        "par",
        "pour",
        "sur",
        "un",
        "une",
    ]
)


@dataclass
class ResultatTracage:
    recette: Recette | None
    retraits: list[str] = field(default_factory=list)

    @property
    def huiles_retirees(self) -> bool:
        return any(r.startswith("HE ") for r in self.retraits)


def _motif_nombre(valeur: float) -> re.Pattern[str]:
    if valeur == int(valeur):
        entier = str(int(valeur))
        corps = rf"{entier}(?:[.,]0+)?"
    else:
        texte = f"{valeur:g}"
        entier, decimales = texte.split(".")
        corps = rf"{entier}[.,]{decimales}0*"
    return re.compile(rf"(?<![\d.,]){corps}(?![\d]|[.,]\d)")


def nombre_present(valeur: float, texte: str) -> bool:
    return bool(_motif_nombre(valeur).search(texte))


def he_mentionnee(he_id: str, texte: str, referentiel: Referentiel) -> bool:
    huile = referentiel.get(he_id)
    if huile is None:
        return False
    t = f" {simplifier(texte)} "
    return any(f" {simplifier(nom)} " in t for nom in huile.tous_les_noms())


def _mots(texte: str) -> set[str]:
    return {m for m in simplifier(texte).split() if m not in _MOTS_VIDES}


_NEGATIONS = frozenset({"ne", "n", "pas", "jamais", "ni", "sans", "aucun", "aucune", "eviter"})


def _negative(mots: set[str]) -> bool:
    return bool(mots & _NEGATIONS)


def precaution_presente(texte_precaution: str, texte_source: str) -> bool:
    """Vrai si une phrase de la source porte la précaution, avec la même polarité.

    La comparaison se fait phrase par phrase pour qu'une négation (« ne pas appliquer »)
    ne puisse pas tracer la consigne inverse (« appliquer »).
    """
    mots = _mots(texte_precaution)
    if not mots:
        return False
    for phrase in re.split(r"[.!?;\n]+", texte_source):
        mots_phrase = _mots(phrase)
        if len(mots & mots_phrase) / len(mots) >= _SEUIL_PRECAUTION and _negative(
            mots
        ) == _negative(mots_phrase):
            return True
    return False


def _dose_tracee(dose: DoseHE, textes: dict[str, str], referentiel: Referentiel) -> list[str]:
    """URL citées qui tracent effectivement la dose."""
    return [
        url
        for url in dose.sources
        if url in textes
        and he_mentionnee(dose.he_id, textes[url], referentiel)
        and nombre_present(dose.quantite.valeur, textes[url])
    ]


def tracer(recette: Recette, textes: dict[str, str], referentiel: Referentiel) -> ResultatTracage:
    """Retire tout élément non tracé ; `recette` vaut `None` s'il ne reste aucune HE.

    `textes` associe chaque URL récupérée au texte de la page (ou de l'extrait).
    """
    retraits: list[str] = []
    huiles: list[DoseHE] = []
    for dose in recette.huiles:
        tracees = _dose_tracee(dose, textes, referentiel)
        if tracees:
            huiles.append(dose.model_copy(update={"sources": tracees}))
        else:
            retraits.append(f"HE {dose.he_id} retirée : aucune source citée ne la mentionne")
    precautions: list[Precaution] = []
    for precaution in recette.precautions:
        tracees = [
            url
            for url in precaution.sources
            if url in textes and precaution_presente(precaution.texte, textes[url])
        ]
        if tracees:
            precautions.append(precaution.model_copy(update={"sources": tracees}))
        else:
            retraits.append(f"Précaution retirée (non tracée) : {precaution.texte}")
    if not huiles:
        return ResultatTracage(recette=None, retraits=retraits)
    sources = sorted(
        {url for h in huiles for url in h.sources} | {url for p in precautions for url in p.sources}
    )
    tracee = recette.model_copy(
        update={"huiles": huiles, "precautions": precautions, "sources": sources}
    )
    return ResultatTracage(recette=tracee, retraits=retraits)
