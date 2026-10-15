import pytest

from agent_he.safety.keywords import charger_filet

from aides import DOSSIER_DONNEES, questionnaire

FILET = charger_filet(DOSSIER_DONNEES)


@pytest.mark.parametrize(
    ("texte", "categorie"),
    [
        ("je suis enceinte de 5 mois", "grossesse_allaitement"),
        ("Je suis à 22 SA", "grossesse_allaitement"),
        ("deuxième trimestre", "grossesse_allaitement"),
        ("j'allaite mon bébé", "grossesse_allaitement"),
        ("mon fils est épileptique", "epilepsie"),
        ("crise d'épilepsie l'an dernier", "epilepsie"),
        ("je suis asthmatique", "asthme"),
        ("ASTHME léger", "asthme"),
        ("sous anticoagulants", "traitement"),
        ("pour ma fille de 4 ans", "age"),
        ("bébé de 18 mois", "age"),
    ],
)
def test_detection(texte: str, categorie: str) -> None:
    assert categorie in FILET.detecter(texte)


@pytest.mark.parametrize(
    "texte", ["un mélange pour dormir", "odeur agréable en diffusion", "massage du dos", ""]
)
def test_pas_de_faux_positif(texte: str) -> None:
    assert FILET.detecter(texte) == set()


def test_risque_non_coche_demande_confirmation() -> None:
    q = questionnaire()
    assert FILET.risques_non_coches("je suis enceinte", q) == ["grossesse ou allaitement"]
    assert FILET.risques_non_coches("pour mon fils de 4 ans", q) == ["enfant ou adolescent"]


def test_risque_deja_coche_silencieux() -> None:
    q = questionnaire(grossesse_allaitement=True, age="de_6_a_12")
    assert FILET.risques_non_coches("enceinte, pour ma fille de 8 ans", q) == []
