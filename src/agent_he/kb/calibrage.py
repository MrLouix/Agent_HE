"""Calibrage du seuil de correspondance de la priorité 1 (spécification §6, §12).

Le seuil dépend du plongeur : un sac de mots haché donne des similarités bien plus
faibles que des plongements sémantiques. Il est calibré sur des paires (demande, recette)
étiquetées « pertinente » ou non (`tests/eval/correspondance.yaml`).
"""

from collections.abc import Sequence

# Valeurs par défaut issues du calibrage (voir tests/eval/test_calibrage.py).
SEUILS_PAR_PLONGEUR: dict[str, float] = {"local": 0.2, "mistral": 0.8}


def calibrer(scores: Sequence[tuple[float, bool]]) -> float:
    """Seuil maximisant le F1, placé au milieu de l'écart avec le score inférieur.

    À F1 égal, le seuil le plus exigeant l'emporte (prudence) ; le placer au milieu de
    l'écart évite qu'un score pertinent tombe juste sous le seuil à la moindre variation.
    """
    if not any(p for _, p in scores):
        raise ValueError("aucune paire pertinente pour calibrer")
    valeurs = sorted({s for s, _ in scores})
    meilleur, meilleur_f1 = valeurs[-1], -1.0
    for seuil in valeurs:
        vp = sum(1 for s, p in scores if s >= seuil and p)
        fp = sum(1 for s, p in scores if s >= seuil and not p)
        fn = sum(1 for s, p in scores if s < seuil and p)
        f1 = 2 * vp / (2 * vp + fp + fn)
        if f1 >= meilleur_f1:
            meilleur, meilleur_f1 = seuil, f1
    inferieurs = [v for v in valeurs if v < meilleur]
    return (meilleur + inferieurs[-1]) / 2 if inferieurs else meilleur


def seuil_par_defaut(plongeur: str) -> float:
    return SEUILS_PAR_PLONGEUR[plongeur]
