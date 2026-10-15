"""Pipeline web sur fixtures (phase 3) : aucune requête réseau."""

from typing import Any

import pytest

from agent_he.llm.base import FakeLLM
from agent_he.models import Demande
from agent_he.pipeline.agent import Agent, Reglages
from agent_he.search.reliability import charger_fiabilite

import web
from aides import DOSSIER_DONNEES, questionnaire, referentiel, table_test


def agent(llm: FakeLLM, **kwargs: Any) -> Agent:
    return Agent(
        llm=llm,
        recherche=kwargs.pop("recherche", web.recherche()),
        recuperateur=kwargs.pop("recuperateur", web.recuperateur()),
        table=table_test(),
        referentiel=referentiel(),
        fiabilite=charger_fiabilite(DOSSIER_DONNEES),
        reglages=Reglages(**kwargs),
    )


def demande(**q: Any) -> Demande:
    return Demande(besoin="mieux dormir", voies=["cutanee"], questionnaire=questionnaire(**q))


def test_recette_publiee() -> None:
    reponse = agent(web.llm_fidele()).repondre(demande())
    fiche = reponse.fiche
    assert fiche.mode == "publiee", reponse.notes
    assert fiche.recette is not None
    assert fiche.recette.nom_recette == "Roll-on sommeil apaisant"
    assert any("Recette publiée" in b and "aroma-zone.com" in b for b in fiche.badges)
    assert [str(s.url) for s in reponse.sources] == [web.URL_SOMMEIL]
    textes = [p.texte for p in fiche.recette.precautions]
    assert "Ne pas appliquer sur les muqueuses." in textes


def test_profil_exclu_aucune_recherche() -> None:
    recherche = web.recherche(echouer=True)
    llm = web.llm_fidele()
    reponse = agent(llm, recherche=recherche).repondre(demande(grossesse_allaitement=True))
    assert reponse.fiche.mode == "refus"
    assert reponse.fiche.he_a_eviter == ["sauge_officinale"]
    assert recherche.requetes == []
    assert llm.appels == []


def test_seule_la_liste_blanche_par_defaut() -> None:
    recherche = web.recherche()
    reponse = agent(web.llm_fidele(), recherche=recherche).repondre(demande())
    assert all(domaines is not None for _, domaines in recherche.requetes)
    assert web.URL_BLOG not in {str(s.url) for s in reponse.sources}


def test_passage_ouvert_optionnel() -> None:
    recherche = web.recherche()
    agent(web.llm_fidele(), recherche=recherche, recherche_ouverte=True).repondre(demande())
    assert [d is None for _, d in recherche.requetes] == [False, True]


def test_page_d_injection_ecartee() -> None:
    llm = web.llm_fidele()
    reponse = agent(llm).repondre(demande())
    assert any("consignes adressées à une IA" in n for n in reponse.notes)
    assert "CANNELLE" not in str(llm.appels).upper()


def test_injection_sans_aucune_cannelle_meme_si_le_llm_obeit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptation phase 3 : même un LLM compromis ne fait pas apparaître de cannelle."""
    import agent_he.pipeline.agent as module

    monkeypatch.setattr(module, "contient_injection", lambda texte: False)
    reponse = agent(web.llm_compromis()).repondre(demande())
    assert reponse.fiche.recette is None or all(
        h.he_id != "cannelle_ecorce" for h in reponse.fiche.recette.huiles
    )
    fiche = reponse.fiche
    proposee = fiche.recette.model_dump_json() if fiche.recette else ""
    assert "cannelle" not in proposee.lower()
    assert fiche.he_a_eviter == []


def test_toute_url_citee_provient_des_resultats() -> None:
    reponse = agent(web.llm_compromis()).repondre(demande())
    resultats = {web.URL_SOMMEIL, web.URL_INJECTION, web.URL_BLOG}
    fiche = reponse.fiche
    if fiche.recette is not None:
        citees = set(fiche.recette.sources) | {u for h in fiche.recette.huiles for u in h.sources}
        assert citees <= resultats
    assert {str(s.url) for s in reponse.sources} <= resultats


def test_recette_surdosee_rejetee() -> None:
    recherche = web.recherche(web.URL_BLOG)
    reponse = agent(web.llm_fidele(), recherche=recherche, recherche_ouverte=True).repondre(
        demande()
    )
    assert reponse.fiche.mode == "aucune"
    assert any("dépasse le plafond" in n for n in reponse.notes)


def test_erreur_de_recherche() -> None:
    reponse = agent(web.llm_fidele(), recherche=web.recherche(echouer=True)).repondre(demande())
    assert reponse.fiche.mode == "aucune"
    assert "Recherche impossible" in (reponse.fiche.motif or "")


def test_voie_non_demandee_ignoree() -> None:
    d = Demande(besoin="dormir", voies=["diffusion"], questionnaire=questionnaire())
    assert agent(web.llm_fidele()).repondre(d).fiche.mode == "aucune"


def test_recette_amputee_par_la_normalisation_jamais_publiee() -> None:
    """Le LLM compromis cite une source inventée pour la lavande : la recette amputée
    (orange douce seule) n'est pas la recette publiée et ne doit pas être proposée."""
    reponse = agent(web.llm_compromis()).repondre(demande())
    assert reponse.fiche.mode == "aucune"
    assert any("HE non retenue" in n for n in reponse.notes)
