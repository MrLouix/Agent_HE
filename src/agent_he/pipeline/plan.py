"""Plan de recherche : requêtes web dérivées de la demande analysée."""

from agent_he.models import Demande
from agent_he.pipeline.analyze import Analyse

_LIBELLES_VOIES = {
    "diffusion": "diffusion",
    "cutanee": "application cutanée roll-on",
    "bain": "bain",
    "massage": "huile de massage",
    "inhalation": "inhalation",
}


def planifier(demande: Demande, analyse: Analyse, max_requetes: int = 3) -> list[str]:
    """Une requête par voie demandée (sans doublon), enrichie des mots-clés."""
    mots = " ".join([*(str(b) for b in analyse.besoins), *analyse.mots_cles[:3]])
    requetes: list[str] = []
    for voie in demande.voies:
        requete = " ".join(
            p
            for p in ("recette huiles essentielles", demande.besoin, mots, _LIBELLES_VOIES[voie])
            if p
        )
        if requete not in requetes:
            requetes.append(requete)
    return requetes[:max_requetes]
