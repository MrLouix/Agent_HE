"""Aides partagées par les tests.

⚠️ Les valeurs numériques des entrées de sécurité fabriquées ici sont FICTIVES et ne
servent qu'aux tests : elles ne proviennent d'aucune source et ne doivent jamais être
recopiées dans data/securite.yaml.
"""

from datetime import date
from itertools import count
from pathlib import Path
from typing import Any

from agent_he.referentiel.huiles import Referentiel, charger_referentiel
from agent_he.referentiel.securite import EntreeSecurite, valider, verifier

RACINE = Path(__file__).resolve().parents[1]
DOSSIER_DONNEES = RACINE / "data"
FIXTURES = RACINE / "tests" / "fixtures"

_compteur = count(9000)


def referentiel() -> Referentiel:
    return charger_referentiel(DOSSIER_DONNEES)


def entree(statut: str = "valide", **champs: Any) -> EntreeSecurite:
    """Entrée de sécurité FICTIVE ; `statut` = brouillon | verifie | valide | retire."""
    donnees: dict[str, Any] = {
        "id": f"SEC-{next(_compteur)}",
        "type": "plafond",
        "he_id": "lavande_vraie",
        "nom_latin": "Lavandula angustifolia",
        "voie": "cutanee",
        "population": "adulte",
        "valeur": 5,
        "unite": "%",
        "source": {
            "ouvrage": "Ouvrage fictif de test",
            "page": 1,
            "localisation": "test",
            "citation": "valeur fictive de test",
        },
        "saisie": {"par": "testeur", "le": "2026-01-01", "methode": "manuelle"},
    }
    if champs.get("he_id") == "*":
        donnees.pop("nom_latin")
    if champs.get("type") in ("drapeau", "interdit_profil"):
        for cle in ("voie", "population", "valeur", "unite"):
            donnees.pop(cle)
    donnees.update(champs)
    e = EntreeSecurite.model_validate(donnees)
    if statut == "brouillon":
        return e
    if statut == "retire":
        return e.model_copy(update={"statut": "retire", "motif_retrait": "test"})
    e = verifier(e, par="relecteur", le=date(2026, 1, 2), conforme=True)
    if statut == "verifie":
        return e
    return valider(e, par="relecteur", le=date(2026, 1, 3))


def plafond(he_id: str, valeur: float, voie: str = "cutanee", **champs: Any) -> EntreeSecurite:
    latin = referentiel()[he_id].nom_latin
    return entree(he_id=he_id, nom_latin=latin, valeur=valeur, voie=voie, **champs)


def plafond_total(valeur: float, voie: str = "cutanee", **champs: Any) -> EntreeSecurite:
    return entree(type="plafond_total", he_id="*", valeur=valeur, voie=voie, **champs)


def drapeau(he_id: str, drapeau: str, statut: str = "valide", **champs: Any) -> EntreeSecurite:
    latin = referentiel()[he_id].nom_latin
    return entree(
        statut=statut, type="drapeau", he_id=he_id, nom_latin=latin, drapeau=drapeau, **champs
    )


def interdit(he_id: str, profil: str, statut: str = "valide", **champs: Any) -> EntreeSecurite:
    latin = referentiel()[he_id].nom_latin
    return entree(
        statut=statut, type="interdit_profil", he_id=he_id, nom_latin=latin, profil=profil, **champs
    )
