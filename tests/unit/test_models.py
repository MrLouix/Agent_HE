from typing import Any

import pytest
from pydantic import ValidationError

from agent_he.models import (
    AVERTISSEMENT_SYNTHESE,
    Demande,
    DoseHE,
    EntreeUsage,
    Fiche,
    Produit,
    Quantite,
    Questionnaire,
    Recette,
    Source,
    StatsHE,
    TrancheAge,
    Voie,
)


def _dose(**surcharges: Any) -> DoseHE:
    valeurs: dict[str, Any] = {
        "he_id": "lavande_vraie",
        "nom": "Lavande vraie",
        "nom_latin": "Lavandula angustifolia",
        "chemotype": "linalol",
        "quantite": Quantite(valeur=3, unite="gouttes"),
        "sources": ["https://exemple.fr/recette"],
    }
    valeurs.update(surcharges)
    return DoseHE(**valeurs)


def _recette() -> Recette:
    return Recette(
        nom_recette="Mélange diffusion sommeil",
        voie=Voie.DIFFUSION,
        huiles=[_dose()],
        base_description="eau + dispersant",
        base_volume_ml=100,
    )


def _questionnaire() -> Questionnaire:
    return Questionnaire(age=TrancheAge.ADULTE)


# --- Voie orale exclue (spec §0) --------------------------------------------------


def test_voie_orale_n_existe_pas() -> None:
    assert "orale" not in {voie.value for voie in Voie}
    with pytest.raises(ValueError):
        Voie("orale")


def test_demande_refuse_la_voie_orale() -> None:
    with pytest.raises(ValidationError):
        Demande.model_validate(
            {"besoin": "digestion", "voies": ["orale"], "questionnaire": {"age": "adulte"}}
        )


def test_recette_refuse_la_voie_orale() -> None:
    donnees = _recette().model_dump()
    donnees["voie"] = "orale"
    with pytest.raises(ValidationError):
        Recette.model_validate(donnees)


# --- Demande et questionnaire ----------------------------------------------------


def test_demande_valide() -> None:
    demande = Demande.model_validate(
        {
            "besoin": "  mieux dormir  ",
            "voies": ["diffusion"],
            "questionnaire": {"age": "adulte", "asthme": True},
        }
    )
    assert demande.besoin == "mieux dormir"
    assert demande.questionnaire.asthme is True
    assert demande.questionnaire.epilepsie is False


@pytest.mark.parametrize("surcharge", [{"besoin": "   "}, {"voies": []}, {"inconnu": "champ"}])
def test_demande_invalide(surcharge: dict[str, Any]) -> None:
    donnees: dict[str, Any] = {
        "besoin": "sommeil",
        "voies": ["diffusion"],
        "questionnaire": {"age": "adulte"},
    }
    donnees.update(surcharge)
    with pytest.raises(ValidationError):
        Demande.model_validate(donnees)


def test_questionnaire_exige_l_age() -> None:
    with pytest.raises(ValidationError):
        Questionnaire.model_validate({})


# --- Quantités et doses ----------------------------------------------------------


@pytest.mark.parametrize(
    ("valeur", "unite"), [(0, "gouttes"), (-1, "ml"), (101, "%"), (2, "cuillères")]
)
def test_quantite_invalide(valeur: float, unite: str) -> None:
    with pytest.raises(ValidationError):
        Quantite.model_validate({"valeur": valeur, "unite": unite})


def test_concentration_bornee() -> None:
    with pytest.raises(ValidationError):
        _dose(concentration_pct=150)


def test_recette_exige_au_moins_une_huile() -> None:
    with pytest.raises(ValidationError):
        Recette(nom_recette="Vide", voie=Voie.BAIN, huiles=[])


# --- Sources et produits ---------------------------------------------------------


def test_source_domaine_calcule() -> None:
    source = Source.model_validate(
        {
            "url": "https://www.Compagnie-des-Sens.fr/lavande",
            "titre": "Lavande vraie",
            "confiance": "commercial",
        }
    )
    assert source.domaine == "compagnie-des-sens.fr"


def test_source_url_invalide() -> None:
    with pytest.raises(ValidationError):
        Source.model_validate({"url": "pas-une-url", "titre": "x", "confiance": "commercial"})


def test_produit_prix_au_ml() -> None:
    produit = Produit.model_validate(
        {
            "boutique": "Boutique",
            "nom": "Lavande",
            "volume_ml": 10,
            "prix": 5.5,
            "url": "https://boutique.example/lavande",
        }
    )
    assert produit.prix_ml == pytest.approx(0.55)


# --- Fiches (spec §6) ------------------------------------------------------------


def test_fiche_refus_sans_recette_et_avec_motif() -> None:
    fiche = Fiche(
        mode="refus",
        motif="Grossesse : aucun dosage proposé.",
        he_a_eviter=["sauge_officinale"],
        convention_gouttes_ml=20,
    )
    assert fiche.recette is None


def test_fiche_refus_ne_peut_pas_porter_de_recette() -> None:
    with pytest.raises(ValidationError):
        Fiche(mode="refus", motif="Grossesse", recette=_recette(), convention_gouttes_ml=20)


@pytest.mark.parametrize("mode", ["refus", "aucune"])
def test_fiche_sans_recette_exige_un_motif(mode: str) -> None:
    with pytest.raises(ValidationError):
        Fiche.model_validate({"mode": mode, "convention_gouttes_ml": 20})


@pytest.mark.parametrize("mode", ["validee", "publiee", "synthese"])
def test_fiche_avec_recette_exige_une_recette(mode: str) -> None:
    with pytest.raises(ValidationError):
        Fiche.model_validate({"mode": mode, "convention_gouttes_ml": 20})


def test_fiche_synthese_porte_toujours_l_avertissement() -> None:
    fiche = Fiche(mode="synthese", recette=_recette(), convention_gouttes_ml=20)
    assert fiche.avertissements[0] == AVERTISSEMENT_SYNTHESE

    deja_present = Fiche(
        mode="synthese",
        recette=_recette(),
        avertissements=[AVERTISSEMENT_SYNTHESE],
        convention_gouttes_ml=20,
    )
    assert deja_present.avertissements.count(AVERTISSEMENT_SYNTHESE) == 1


def test_fiche_validee_sans_avertissement_ia() -> None:
    fiche = Fiche(mode="validee", recette=_recette(), convention_gouttes_ml=20)
    assert AVERTISSEMENT_SYNTHESE not in fiche.avertissements


# --- Journal d'usage (spec §11) --------------------------------------------------


def test_entree_usage_avec_recette() -> None:
    entree = EntreeUsage.model_validate(
        {"recette_ref": "sommeil-01", "voie": "diffusion", "efficacite": 4, "tolerance": "aucune"}
    )
    assert entree.personne == "moi"


def test_entree_usage_avec_melange_libre() -> None:
    entree = EntreeUsage(melange_libre=[_dose()], voie=Voie.CUTANEE, tolerance="legere")
    assert entree.efficacite is None


@pytest.mark.parametrize(
    "surcharge",
    [
        {},  # ni recette ni mélange
        {"recette_ref": "r1", "melange_libre": [{"he_id": "x"}]},  # les deux
        {"melange_libre": []},  # mélange vide
        {"recette_ref": "r1", "efficacite": 6},
        {"recette_ref": "r1", "odeur": 0},
        {"recette_ref": "r1", "tolerance": "inconnue"},
    ],
)
def test_entree_usage_invalide(surcharge: dict[str, Any]) -> None:
    donnees: dict[str, Any] = {"voie": "diffusion", "tolerance": "aucune"}
    donnees.update(surcharge)
    with pytest.raises(ValidationError):
        EntreeUsage.model_validate(donnees)


def test_entree_usage_identifiants_uniques() -> None:
    a = EntreeUsage(recette_ref="r", voie=Voie.BAIN, tolerance="aucune")
    b = EntreeUsage(recette_ref="r", voie=Voie.BAIN, tolerance="aucune")
    assert a.id != b.id


def test_stats_he_bornes() -> None:
    with pytest.raises(ValidationError):
        StatsHE(he_id="lavande_vraie", nb_usages=-1)
    StatsHE(he_id="lavande_vraie", nb_usages=0)
