"""Signal de tolérance (spécification §11.3).

- HE suspectes : présentes dans des mélanges ayant provoqué une réaction et absentes de
  tous les mélanges bien tolérés, classées par nombre de réactions ;
- au-delà d'un seuil (défaut : 1 réaction forte ou 2 légères pour une même HE suspecte),
  une **proposition** d'exclusion est faite. Rien n'est exclu sans confirmation.
"""

from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from agent_he.journal.stats import Entrees
from agent_he.models import Tolerance


@dataclass(frozen=True)
class Suspecte:
    he_id: str
    nb_reactions: int
    nb_fortes: int
    nb_legeres: int
    entrees: tuple[UUID, ...]


@dataclass(frozen=True)
class Proposition:
    he_id: str
    motif: str
    entrees: tuple[UUID, ...]


def he_suspectes(entrees: Entrees) -> list[Suspecte]:
    tolerees = {h for e, huiles in entrees if e.tolerance == Tolerance.AUCUNE for h in huiles}
    fortes: Counter[str] = Counter()
    legeres: Counter[str] = Counter()
    liens: dict[str, list[UUID]] = {}
    for entree, huiles in entrees:
        if entree.tolerance == Tolerance.AUCUNE:
            continue
        for he_id in huiles:
            if he_id in tolerees:
                continue
            compteur = fortes if entree.tolerance == Tolerance.FORTE else legeres
            compteur[he_id] += 1
            liens.setdefault(he_id, []).append(entree.id)
    suspectes = [
        Suspecte(h, fortes[h] + legeres[h], fortes[h], legeres[h], tuple(liens[h])) for h in liens
    ]
    return sorted(suspectes, key=lambda s: (-s.nb_fortes, -s.nb_reactions, s.he_id))


def suspectes_pour(entrees: Entrees, entree_id: UUID) -> list[str]:
    """HE suspectes d'un mélange donné ayant provoqué une réaction."""
    huiles = next((h for e, h in entrees if e.id == entree_id), [])
    return [s.he_id for s in he_suspectes(entrees) if s.he_id in huiles]


def propositions_exclusion(
    entrees: Entrees,
    deja_exclues: set[str],
    seuil_fortes: int = 1,
    seuil_legeres: int = 2,
) -> list[Proposition]:
    propositions: list[Proposition] = []
    for s in he_suspectes(entrees):
        if s.he_id in deja_exclues:
            continue
        if s.nb_fortes >= seuil_fortes or s.nb_legeres >= seuil_legeres:
            motif = (
                f"{s.nb_fortes} réaction(s) forte(s) et {s.nb_legeres} légère(s) "
                "avec des mélanges la contenant"
            )
            propositions.append(Proposition(s.he_id, motif, s.entrees))
    return propositions
