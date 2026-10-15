"""Filet de détection des risques dans le texte libre (spécification §8).

Ce filet ne décide rien : il signale un risque non coché, et l'interface demande
confirmation à l'utilisateur.
"""

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

from agent_he.models import Questionnaire, TrancheAge

_LIBELLES = {
    "grossesse_allaitement": "grossesse ou allaitement",
    "epilepsie": "épilepsie",
    "asthme": "asthme",
    "traitement": "traitement médicamenteux",
    "pathologie_hormonale": "pathologie hormonodépendante",
    "age": "enfant ou adolescent",
}


def _normaliser(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in decompose if not unicodedata.combining(c))


class FiletMotsCles:
    def __init__(self, motifs: dict[str, list[str]]) -> None:
        self._motifs = {cat: [re.compile(m) for m in liste] for cat, liste in motifs.items()}

    @classmethod
    def depuis_fichier(cls, chemin: Path) -> "FiletMotsCles":
        donnees = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
        return cls({str(k): [str(m) for m in v or []] for k, v in donnees.items()})

    def detecter(self, texte: str) -> set[str]:
        """Catégories de risque mentionnées dans le texte."""
        t = _normaliser(texte)
        return {cat for cat, motifs in self._motifs.items() if any(m.search(t) for m in motifs)}

    def risques_non_coches(self, texte: str, q: Questionnaire) -> list[str]:
        """Risques détectés dans le texte mais absents du questionnaire (à confirmer)."""
        coches = {
            "grossesse_allaitement": q.grossesse_allaitement,
            "epilepsie": q.epilepsie,
            "asthme": q.asthme,
            "traitement": q.traitement,
            "pathologie_hormonale": q.pathologie_hormonale,
            "age": q.age not in (TrancheAge.ADULTE, TrancheAge.PLUS_65),
        }
        return sorted(
            _LIBELLES.get(cat, cat) for cat in self.detecter(texte) if not coches.get(cat, False)
        )


@lru_cache
def charger_filet(dossier_donnees: Path) -> FiletMotsCles:
    return FiletMotsCles.depuis_fichier(dossier_donnees / "mots_cles_risque.yaml")
