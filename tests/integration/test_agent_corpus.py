"""Priorité 1a (corpus) et 1b (web ⇒ file de validation) — phase 4."""

from typing import Any

from agent_he.kb.embeddings import PlongeurLocal
from agent_he.kb.store import MagasinMemoire
from agent_he.kb.validation import FileValidation
from agent_he.models import Demande
from agent_he.pipeline.agent import Agent, Reglages
from agent_he.search.reliability import charger_fiabilite
from agent_he.storage.db import connecter

import web
from aides import DOSSIER_DONNEES, questionnaire, recette_corpus, referentiel, table_test


def agent(recherche: Any, corpus: list[Any], **kwargs: Any) -> Agent:
    magasin = MagasinMemoire(PlongeurLocal())
    magasin.indexer(corpus)
    return Agent(
        llm=kwargs.pop("llm", web.llm_fidele()),
        recherche=recherche,
        recuperateur=web.recuperateur(),
        table=table_test(),
        referentiel=referentiel(),
        fiabilite=charger_fiabilite(DOSSIER_DONNEES),
        reglages=Reglages(seuil_correspondance=kwargs.pop("seuil", 0.3)),
        magasin=magasin,
        corpus={r.id: r for r in corpus},
        file_validation=kwargs.pop("file_validation", None),
    )


def demande(**q: Any) -> Demande:
    return Demande(besoin="mieux dormir", voies=["cutanee"], questionnaire=questionnaire(**q))


def test_recette_du_corpus_sans_appel_web() -> None:
    """Acceptation phase 4 : la recherche web échoue si elle est appelée."""
    recherche = web.recherche(echouer=True)
    reponse = agent(recherche, [recette_corpus()]).repondre(demande())
    assert reponse.fiche.mode == "validee"
    assert recherche.requetes == []
    assert any(b.startswith("✅ Recette validée") for b in reponse.fiche.badges)
    assert [str(s.url) for s in reponse.sources] == ["https://www.aroma-zone.com/recette-a"]


def test_recette_du_corpus_non_conforme_ecartee() -> None:
    reponse = agent(web.recherche(), [recette_corpus()]).repondre(demande(traitement=True))
    assert reponse.fiche.mode == "validee"  # lavande + orange : pas d'interaction
    exclue = agent(web.recherche(), [recette_corpus()]).repondre(demande())
    assert exclue.fiche.mode == "validee"
    perso = agent(web.recherche(), [recette_corpus()]).repondre(
        demande(), exclusions_perso={"orange_douce"}
    )
    assert perso.fiche.mode != "validee"
    assert any("exclusion personnelle" in n for n in perso.notes)


def test_seuil_de_similarite() -> None:
    recherche = web.recherche()
    reponse = agent(recherche, [recette_corpus()], seuil=0.99).repondre(demande())
    assert reponse.fiche.mode == "publiee"
    assert recherche.requetes


def test_besoin_different_bascule_sur_le_web() -> None:
    d = Demande(besoin="soin des boutons", voies=["cutanee"], questionnaire=questionnaire())
    recherche = web.recherche()
    agent(recherche, [recette_corpus()]).repondre(d)
    assert recherche.requetes


def test_recette_web_ajoutee_a_la_file_de_validation() -> None:
    file = FileValidation(connecter(":memory:"))
    reponse = agent(web.recherche(), [], file_validation=file).repondre(demande())
    assert reponse.fiche.mode == "publiee"
    (candidate,) = file.lister()
    assert candidate.recette.nom_recette == "Roll-on sommeil apaisant"
    assert candidate.confiance == "commercial"
    assert [str(b) for b in candidate.besoins] == ["sommeil"]
