"""Demandes hors périmètre (spécification §0) : animaux et ingestion.

Contrôlé par le code, avant toute recherche : une telle demande reçoit un refus
explicatif, jamais un dosage.
"""

import re
import unicodedata

_ANIMAUX = re.compile(
    r"\b(chats?|chatons?|chiens?|chiots?|chevaux|cheval|lapins?|animal|animaux|oiseaux?|"
    r"perroquets?|hamsters?|furets?|cochons? d.inde|veterinaire|cats?|dogs?|pets?)\b"
)
_INGESTION = re.compile(
    r"\b(avaler|boire|ingerer|ingestion|ingere|voie orale|par voie interne|usage interne|"
    r"gelules?|capsules?|comprimes?|sous la langue|sublingual|per os|"
    r"dans (un|une|mon|ma|le|la) (the|tisane|verre|cafe|infusion|cuillere)|"
    r"cuilleree? de miel|swallow|drink|oral use)\b"
)

MOTIF_ANIMAUX = (
    "Les animaux sont hors du périmètre de l'outil : certains, comme le chat, ne "
    "métabolisent pas des composés des huiles essentielles. Demande conseil à un vétérinaire."
)
MOTIF_INGESTION = (
    "L'ingestion d'huiles essentielles est hors du périmètre de l'outil (automédication "
    "orale déconseillée). Demande conseil à un médecin ou à un pharmacien."
)


def _normaliser(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in decompose if not unicodedata.combining(c))


def hors_perimetre(texte: str) -> str | None:
    """Motif de refus si la demande vise un animal ou une ingestion, sinon `None`."""
    t = _normaliser(texte)
    if _ANIMAUX.search(t):
        return MOTIF_ANIMAUX
    if _INGESTION.search(t):
        return MOTIF_INGESTION
    return None
