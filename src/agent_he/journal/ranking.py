"""Classement personnalisé (spécification §11.3, §11.4).

Il ne fait qu'**ordonner** des recettes déjà conformes : il ne filtre rien en faveur
d'une recette non conforme et ne réintroduit jamais une recette écartée. Bonus et malus
sont bornés pour ne jamais écraser la pertinence.
"""

from collections.abc import Callable, Sequence
from typing import TypeVar

from agent_he.journal.stats import Entrees, preferences_olfactives, stats_par_he, stats_recette
from agent_he.models import Recette

BORNE = 0.3

T = TypeVar("T")


def score_journal(recette: Recette, recette_ref: str | None, entrees: Entrees) -> float:
    """Bonus/malus dans [-BORNE, +BORNE]."""
    score = 0.0
    stats = stats_recette(entrees, recette_ref) if recette_ref else None
    if stats is not None:
        if stats.efficacite_moy is not None:
            score += (stats.efficacite_moy - 3) / 2 * 0.15
        if stats.odeur_moy is not None:
            score += (stats.odeur_moy - 3) / 2 * 0.1
        if stats.reactions:
            score -= 0.15
    prefs = preferences_olfactives(entrees)
    he_ids = {h.he_id for h in recette.huiles}
    score += 0.05 * len(he_ids & set(prefs.appreciees))
    score -= 0.05 * len(he_ids & set(prefs.detestees))
    par_he = stats_par_he(entrees)
    if any(
        par_he[h].nb_reactions_fortes + par_he[h].nb_reactions_legeres
        for h in he_ids & par_he.keys()
    ):
        score -= 0.05
    return max(-BORNE, min(BORNE, score))


def classer(
    candidates: Sequence[T],
    entrees: Entrees,
    recette: Callable[[T], Recette],
    ref: Callable[[T], str | None],
    pertinence: Callable[[T], float],
) -> list[T]:
    """Même ensemble de recettes, réordonné par pertinence + score du journal."""
    return sorted(
        candidates,
        key=lambda c: pertinence(c) + score_journal(recette(c), ref(c), entrees),
        reverse=True,
    )
