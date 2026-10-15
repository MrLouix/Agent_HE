"""Calcul des doses (spécification §7) : tout est fait ici, jamais par le LLM.

L'unité de référence est la concentration en % (volume d'HE / volume de la base).
Rapporter au volume de la base plutôt qu'au volume final surestime très légèrement la
concentration : l'écart va dans le sens de la prudence. Les gouttes ne sont qu'un
affichage dérivé, selon une convention gouttes/ml configurable et affichée.
"""

import math
from dataclasses import dataclass

from agent_he.models import DoseHE, Quantite, Recette

_DECIMALES_PCT = 4


@dataclass(frozen=True)
class Affichage:
    pourcentage: float | None
    ml: float | None
    gouttes: float | None


def volume_ml(
    quantite: Quantite, convention_gouttes_ml: int, base_volume_ml: float | None
) -> float | None:
    """Volume d'HE en ml, ou `None` s'il n'est pas calculable."""
    if quantite.unite == "ml":
        return quantite.valeur
    if quantite.unite == "gouttes":
        return quantite.valeur / convention_gouttes_ml
    if base_volume_ml is None:
        return None
    return quantite.valeur * base_volume_ml / 100


def concentration_pct(
    quantite: Quantite, base_volume_ml: float | None, convention_gouttes_ml: int
) -> float | None:
    """Concentration en %, ou `None` si elle n'est pas calculable (pas de base connue)."""
    if quantite.unite == "%":
        return quantite.valeur
    if base_volume_ml is None:
        return None
    volume = volume_ml(quantite, convention_gouttes_ml, base_volume_ml)
    assert volume is not None
    return round(volume / base_volume_ml * 100, _DECIMALES_PCT)


def gouttes(ml: float, convention_gouttes_ml: int) -> float:
    return ml * convention_gouttes_ml


def affichage(dose: DoseHE, base_volume_ml: float | None, convention_gouttes_ml: int) -> Affichage:
    """% + ml + gouttes (indicatif) pour une dose."""
    pct = concentration_pct(dose.quantite, base_volume_ml, convention_gouttes_ml)
    ml = volume_ml(dose.quantite, convention_gouttes_ml, base_volume_ml)
    return Affichage(
        pourcentage=pct,
        ml=None if ml is None else round(ml, 3),
        gouttes=None if ml is None else round(gouttes(ml, convention_gouttes_ml), 1),
    )


def avec_concentrations(recette: Recette, convention_gouttes_ml: int) -> Recette:
    """Copie de la recette où `concentration_pct` est calculée par le code pour chaque HE."""
    huiles = [
        h.model_copy(
            update={
                "concentration_pct": concentration_pct(
                    h.quantite, recette.base_volume_ml, convention_gouttes_ml
                )
            }
        )
        for h in recette.huiles
    ]
    return recette.model_copy(update={"huiles": huiles})


def total_pct(recette: Recette, convention_gouttes_ml: int) -> float | None:
    """Concentration totale du mélange, ou `None` si une concentration n'est pas calculable."""
    valeurs = [
        concentration_pct(h.quantite, recette.base_volume_ml, convention_gouttes_ml)
        for h in recette.huiles
    ]
    if any(v is None for v in valeurs):
        return None
    return round(sum(v for v in valeurs if v is not None), _DECIMALES_PCT)


def dose_pour_concentration(
    pct: float, base_volume_ml: float, convention_gouttes_ml: int
) -> Quantite:
    """Quantité en ml donnant la concentration `pct` dans `base_volume_ml`."""
    del convention_gouttes_ml  # la quantité de référence est en ml ; les gouttes sont dérivées
    # Arrondi par défaut : la concentration obtenue ne dépasse jamais `pct`.
    ml = math.floor(pct * base_volume_ml / 100 * 10_000 + 1e-9) / 10_000
    return Quantite(valeur=ml, unite="ml")


def mettre_a_echelle(
    recette: Recette, nouveau_volume_ml: float, convention_gouttes_ml: int
) -> Recette:
    """Adapte la recette à un autre volume en conservant chaque concentration (§7).

    Lève `ValueError` si une concentration n'est pas calculable.
    """
    if nouveau_volume_ml <= 0:
        raise ValueError("le volume doit être positif")
    huiles: list[DoseHE] = []
    for h in recette.huiles:
        pct = concentration_pct(h.quantite, recette.base_volume_ml, convention_gouttes_ml)
        if pct is None:
            raise ValueError(f"concentration non calculable pour {h.he_id}")
        if h.quantite.unite == "%":
            huiles.append(h.model_copy(update={"concentration_pct": pct}))
            continue
        quantite = dose_pour_concentration(pct, nouveau_volume_ml, convention_gouttes_ml)
        huiles.append(h.model_copy(update={"quantite": quantite, "concentration_pct": pct}))
    return recette.model_copy(update={"huiles": huiles, "base_volume_ml": nouveau_volume_ml})
