"""Aides partagées par les tests.

⚠️ Les valeurs numériques des entrées de sécurité fabriquées ici sont FICTIVES et ne
servent qu'aux tests : elles ne proviennent d'aucune source et ne doivent jamais être
recopiées dans data/securite.yaml.
"""

from datetime import date
from functools import lru_cache
from itertools import count
from pathlib import Path
from typing import Any

from agent_he.kb.corpus import RecetteCorpus
from agent_he.models import DoseHE, Quantite, Questionnaire, Recette
from agent_he.referentiel.huiles import Referentiel, charger_referentiel
from agent_he.referentiel.securite import EntreeSecurite, TableSecurite, valider, verifier

RACINE = Path(__file__).resolve().parents[1]
DOSSIER_DONNEES = RACINE / "data"
FIXTURES = RACINE / "tests" / "fixtures"

_compteur = count(9000)


@lru_cache
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


# --- Table de sécurité et recettes de test (valeurs FICTIVES) ---------------------------

URL_A = "https://www.aroma-zone.com/recette-a"
URL_B = "https://www.compagnie-des-sens.fr/recette-b"


def entrees_test() -> list[EntreeSecurite]:
    return [
        plafond("lavande_vraie", 5),
        plafond("tea_tree", 5),
        plafond("orange_douce", 4),
        plafond("cannelle_ecorce", 0.1),
        plafond("gaultherie", 2),
        plafond("sauge_sclaree", 3),
        plafond("bergamote", 0.4),
        plafond("lavande_vraie", 3, voie="massage"),
        plafond("lavande_vraie", 2, population="de_6_a_12"),
        plafond_total(6),
        plafond_total(4, voie="massage"),
        plafond_total(3, population="de_6_a_12"),
        interdit("sauge_officinale", "grossesse_allaitement"),
        interdit("sauge_officinale", "epilepsie"),
        interdit("romarin_camphre", "epilepsie"),
        interdit("eucalyptus_globuleux", "asthme"),
        interdit("menthe_poivree", "de_3_a_6"),
        interdit("menthe_poivree", "moins_3"),
        drapeau("gaultherie", "interaction_medicament", detail="anticoagulants"),
        drapeau("sauge_sclaree", "hormone_like"),
        drapeau("bergamote", "phototoxique"),
        drapeau("cannelle_ecorce", "dermocaustique"),
        drapeau("tea_tree", "allergene", statut="brouillon"),
    ]


def table_test() -> TableSecurite:
    return TableSecurite(entrees_test())


def dose(
    he_id: str, valeur: float, unite: str = "gouttes", url: str = URL_A, **champs: Any
) -> DoseHE:
    huile = referentiel()[he_id]
    return DoseHE(
        he_id=he_id,
        nom=huile.nom,
        nom_latin=huile.nom_latin,
        quantite=Quantite(valeur=valeur, unite=unite),  # type: ignore[arg-type]
        sources=[url],
        **champs,
    )


def recette(
    *doses: DoseHE, voie: str = "cutanee", base_volume_ml: float | None = 10, **champs: Any
) -> Recette:
    return Recette.model_validate(
        {
            "nom_recette": champs.pop("nom_recette", "Recette de test"),
            "voie": voie,
            "huiles": [d.model_dump() for d in doses],
            "base_description": "huile végétale",
            "base_volume_ml": base_volume_ml,
            "sources": sorted({u for d in doses for u in d.sources}),
            **champs,
        }
    )


def questionnaire(**champs: Any) -> Questionnaire:
    return Questionnaire.model_validate({"age": "adulte", **champs})


def recette_corpus(**champs: Any) -> RecetteCorpus:
    """Recette de corpus FICTIVE (pour les tests uniquement)."""
    valeurs: dict[str, Any] = {
        "id": "roll-on-sommeil",
        "besoins": ["sommeil"],
        "mots_cles": ["endormissement", "soir"],
        "confiance": "commercial",
        "recette": recette(
            dose("lavande_vraie", 6), dose("orange_douce", 4), nom_recette="Roll-on sommeil"
        ).model_dump(),
        "validee_par": "testeur",
        "validee_le": "2026-01-05",
    }
    valeurs.update(champs)
    return RecetteCorpus.model_validate(valeurs)
