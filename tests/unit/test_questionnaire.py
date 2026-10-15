import pytest

from agent_he.models import TrancheAge
from agent_he.safety.questionnaire import (
    avertissements_profil,
    he_a_eviter,
    he_exclues,
    profil_exclu,
)

from aides import questionnaire, table_test

TABLE = table_test()


@pytest.mark.parametrize(
    "champs",
    [
        {"grossesse_allaitement": True},
        {"epilepsie": True},
        {"asthme": True},
        {"age": "moins_3"},
        {"age": "de_3_a_6"},
    ],
)
def test_profils_refuses(champs: dict[str, object]) -> None:
    motif = profil_exclu(questionnaire(**champs))
    assert motif is not None
    assert "professionnel" in motif.texte


@pytest.mark.parametrize("age", ["de_6_a_12", "de_12_a_18", "adulte", "plus_65"])
def test_ages_autorises(age: str) -> None:
    assert profil_exclu(questionnaire(age=age)) is None


def test_traitement_et_allergies_ne_refusent_pas() -> None:
    assert profil_exclu(questionnaire(traitement=True, allergies=True)) is None


def test_motifs_cumules() -> None:
    motif = profil_exclu(questionnaire(age="de_3_a_6", asthme=True))
    assert motif is not None
    assert TrancheAge.DE_3_A_6 in motif.profils
    assert "Asthme" in motif.texte


def test_he_a_eviter_grossesse() -> None:
    assert he_a_eviter(questionnaire(grossesse_allaitement=True), TABLE) == ["sauge_officinale"]


def test_he_a_eviter_epilepsie() -> None:
    attendu = ["romarin_camphre", "sauge_officinale"]
    assert he_a_eviter(questionnaire(epilepsie=True), TABLE) == attendu


def test_he_a_eviter_age() -> None:
    assert he_a_eviter(questionnaire(age="de_3_a_6"), TABLE) == ["menthe_poivree"]


def test_traitement_exclut_les_interactions() -> None:
    exclues = he_exclues(questionnaire(traitement=True), TABLE)
    assert "gaultherie" in exclues
    assert "interaction" in exclues["gaultherie"]


def test_pathologie_hormonale_exclut_hormone_like() -> None:
    assert "sauge_sclaree" in he_exclues(questionnaire(pathologie_hormonale=True), TABLE)


def test_adulte_sans_risque_aucune_exclusion() -> None:
    assert he_exclues(questionnaire(), TABLE) == {}


def test_avertissements() -> None:
    textes = " ".join(avertissements_profil(questionnaire(allergies=True, traitement=True)))
    assert "test cutané" in textes
    assert "pharmacien" in textes
    assert avertissements_profil(questionnaire()) == []
