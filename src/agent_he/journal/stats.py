"""Agrégats du journal : par recette, par HE, préférences olfactives (calculs par le code)."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from statistics import mean

from agent_he.models import EntreeUsage, StatsHE, Tolerance

Entrees = Sequence[tuple[EntreeUsage, list[str]]]


@dataclass
class StatsRecette:
    recette_ref: str
    nb_usages: int
    efficacite_moy: float | None
    odeur_moy: float | None
    reactions: list[tuple[datetime, Tolerance]] = field(default_factory=list)


def _moyenne(valeurs: list[int]) -> float | None:
    return round(mean(valeurs), 2) if valeurs else None


def stats_recette(entrees: Entrees, recette_ref: str) -> StatsRecette | None:
    concernees = [e for e, _ in entrees if e.recette_ref == recette_ref]
    if not concernees:
        return None
    return StatsRecette(
        recette_ref=recette_ref,
        nb_usages=len(concernees),
        efficacite_moy=_moyenne([e.efficacite for e in concernees if e.efficacite is not None]),
        odeur_moy=_moyenne([e.odeur for e in concernees if e.odeur is not None]),
        reactions=[
            (e.horodatage, e.tolerance) for e in concernees if e.tolerance != Tolerance.AUCUNE
        ],
    )


def stats_par_he(entrees: Entrees) -> dict[str, StatsHE]:
    groupes: dict[str, list[EntreeUsage]] = defaultdict(list)
    for entree, huiles in entrees:
        for he_id in huiles:
            groupes[he_id].append(entree)
    return {
        he_id: StatsHE(
            he_id=he_id,
            nb_usages=len(liste),
            efficacite_moy=_moyenne([e.efficacite for e in liste if e.efficacite is not None]),
            odeur_moy=_moyenne([e.odeur for e in liste if e.odeur is not None]),
            nb_reactions_legeres=sum(e.tolerance == Tolerance.LEGERE for e in liste),
            nb_reactions_fortes=sum(e.tolerance == Tolerance.FORTE for e in liste),
        )
        for he_id, liste in sorted(groupes.items())
    }


@dataclass
class Preferences:
    appreciees: list[str]
    detestees: list[str]


def preferences_olfactives(
    entrees: Entrees, seuil_haut: float = 4, seuil_bas: float = 2
) -> Preferences:
    """HE dont l'odeur est en moyenne appréciée (≥ 4/5) ou détestée (≤ 2/5)."""
    stats = stats_par_he(entrees)
    return Preferences(
        appreciees=[
            h for h, s in stats.items() if s.odeur_moy is not None and s.odeur_moy >= seuil_haut
        ],
        detestees=[
            h for h, s in stats.items() if s.odeur_moy is not None and s.odeur_moy <= seuil_bas
        ],
    )


def rappel(stats: StatsRecette | None) -> str | None:
    """« d'après ton journal : utilisée 4 fois, efficacité 4/5 »."""
    if stats is None:
        return None
    morceaux = [f"utilisée {stats.nb_usages} fois"]
    if stats.efficacite_moy is not None:
        morceaux.append(f"efficacité {stats.efficacite_moy:g}/5")
    if stats.odeur_moy is not None:
        morceaux.append(f"odeur {stats.odeur_moy:g}/5")
    return "d'après ton journal : " + ", ".join(morceaux)
