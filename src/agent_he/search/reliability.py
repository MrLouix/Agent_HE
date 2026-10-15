"""Domaine ⇒ niveau de confiance (spécification §4, `data/domaines.yaml`)."""

from pathlib import Path

import yaml

from agent_he.models import Confiance
from agent_he.search.base import hote

BADGES: dict[Confiance, str] = {
    Confiance.INSTITUTIONNEL: "🏛️ Institutionnel",
    Confiance.REFERENCE_SECURITE: "🛡️ Référence sécurité",
    Confiance.COMMERCIAL: "🏪 Commercial spécialisé",
    Confiance.NON_VERIFIE: "⚠️ Non vérifié",
}


class Fiabilite:
    def __init__(self, domaines: dict[Confiance, list[str]]) -> None:
        self._domaines = {
            niveau: [d.lower().removeprefix("www.") for d in liste]
            for niveau, liste in domaines.items()
        }

    @classmethod
    def depuis_fichier(cls, chemin: Path) -> "Fiabilite":
        donnees = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
        return cls({Confiance(k): [str(d) for d in v or []] for k, v in donnees.items()})

    def confiance(self, url: str) -> Confiance:
        h = hote(url)
        for niveau in (
            Confiance.INSTITUTIONNEL,
            Confiance.REFERENCE_SECURITE,
            Confiance.COMMERCIAL,
        ):
            if any(h == d or h.endswith("." + d) for d in self._domaines.get(niveau, [])):
                return niveau
        return Confiance.NON_VERIFIE

    def liste_blanche(self) -> list[str]:
        """Domaines de confiance (tous niveaux sauf non vérifié)."""
        return [
            d
            for niveau, liste in self._domaines.items()
            if niveau != Confiance.NON_VERIFIE
            for d in liste
        ]


def charger_fiabilite(dossier_donnees: Path) -> Fiabilite:
    return Fiabilite.depuis_fichier(dossier_donnees / "domaines.yaml")
