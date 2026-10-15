from agent_he.llm.base import FakeLLM
from agent_he.models import Besoin, Demande, Voie
from agent_he.pipeline.analyze import Analyse, analyser
from agent_he.pipeline.plan import planifier
from agent_he.pipeline.synthesize import reservoir, synthetiser
from agent_he.safety.doses import dose_pour_concentration

from aides import URL_A, URL_B, dose, questionnaire, recette, table_test


def test_plan_une_requete_par_voie() -> None:
    d = Demande(besoin="dormir", voies=["cutanee", "diffusion"], questionnaire=questionnaire())
    requetes = planifier(d, Analyse(besoins=[Besoin.SOMMEIL], mots_cles=["soir"]))
    assert len(requetes) == 2
    assert all("dormir" in r and "sommeil" in r and "soir" in r for r in requetes)


def test_analyse_robuste_a_un_llm_en_echec() -> None:
    assert analyser(FakeLLM(["x", "y"]), "mieux dormir").besoins == [Besoin.SOMMEIL]


def test_reservoir_ignore_les_concentrations_incalculables() -> None:
    r1 = recette(dose("lavande_vraie", 6), base_volume_ml=10)
    r2 = recette(dose("orange_douce", 2, url=URL_B), base_volume_ml=None)
    doses = reservoir([r1, r2], 20)
    assert [(d.he_id, d.concentration_pct, d.source) for d in doses] == [
        ("lavande_vraie", 3, URL_A)
    ]


def test_quantite_jamais_au_dessus_de_la_concentration() -> None:
    for pct in (0.1, 1 / 3, 2.5, 5, 4.99999):
        for volume in (5, 10, 30, 7.3):
            ml = dose_pour_concentration(pct, volume, 20).valeur
            assert ml / volume * 100 <= pct + 1e-12


def test_synthese_sans_dose_pour_la_voie() -> None:
    doses = reservoir([recette(dose("lavande_vraie", 6))], 20)
    s = synthetiser(
        FakeLLM([]),
        "x",
        Voie.BAIN,
        doses,
        table_test(),
        questionnaire().age,
        volume_ml=10,
        convention_gouttes_ml=20,
    )
    assert s.recette is None
