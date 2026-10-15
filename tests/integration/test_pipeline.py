"""Pipeline complet (phase 5) : arbre de décision de la spécification §6, sur fixtures."""

from typing import Any

from agent_he.kb.embeddings import PlongeurLocal
from agent_he.kb.store import MagasinMemoire
from agent_he.llm.base import FakeLLM
from agent_he.models import AVERTISSEMENT_SYNTHESE, Demande
from agent_he.pipeline.agent import Agent, Reglages
from agent_he.safety.checks import assert_fiche_sure
from agent_he.search.reliability import charger_fiabilite
from agent_he.storage.audit import JournalAudit
from agent_he.storage.db import connecter

import web
from aides import DOSSIER_DONNEES, questionnaire, recette_corpus, referentiel, table_test

TABLE = table_test()


def agent(llm: FakeLLM, *urls: str, corpus: list[Any] | None = None, **kwargs: Any) -> Agent:
    magasin = MagasinMemoire(PlongeurLocal())
    magasin.indexer(corpus or [])
    return Agent(
        llm=llm,
        recherche=kwargs.pop("recherche", web.recherche(*urls)),
        recuperateur=web.recuperateur(),
        table=TABLE,
        referentiel=referentiel(),
        fiabilite=charger_fiabilite(DOSSIER_DONNEES),
        reglages=Reglages(seuil_correspondance=0.3, recherche_ouverte=True),
        magasin=magasin,
        corpus={r.id: r for r in corpus or []},
        audit=kwargs.pop("audit", None),
    )


def demande(**q: Any) -> Demande:
    return Demande(besoin="mieux dormir", voies=["cutanee"], questionnaire=questionnaire(**q))


def sure(reponse: Any, d: Demande, exclusions: set[str] | None = None) -> None:
    assert_fiche_sure(
        reponse.fiche,
        d.questionnaire,
        TABLE,
        referentiel(),
        voies_demandees=d.voies,
        exclusions_perso=exclusions or set(),
        sources_recuperees={str(s.url) for s in reponse.sources},
    )


SELECTION_LAVANDE = {
    "nom_recette": "Synergie sommeil",
    "huiles": [{"he_id": "lavande_vraie", "source": web.URL_BLOG}],
    "usage": "masser les poignets le soir",
}


def test_1a_corpus() -> None:
    d = demande()
    reponse = agent(web.llm_routeur(), corpus=[recette_corpus()]).repondre(d)
    assert reponse.fiche.mode == "validee"
    assert reponse.recette_ref == "roll-on-sommeil"
    sure(reponse, d)


def test_1b_web() -> None:
    d = demande()
    reponse = agent(web.llm_routeur(), web.URL_SOMMEIL).repondre(d)
    assert reponse.fiche.mode == "publiee"
    sure(reponse, d)


def test_refus() -> None:
    d = demande(epilepsie=True)
    llm = web.llm_routeur()
    reponse = agent(llm, recherche=web.recherche(echouer=True)).repondre(d)
    assert reponse.fiche.mode == "refus"
    assert reponse.fiche.recette is None
    assert reponse.fiche.he_a_eviter == ["romarin_camphre", "sauge_officinale"]
    assert llm.appels == []
    sure(reponse, d)


def test_verbatim_surdosee_bascule_en_synthese() -> None:
    d = demande()
    reponse = agent(web.llm_routeur(selection=SELECTION_LAVANDE), web.URL_BLOG).repondre(d)
    fiche = reponse.fiche
    assert fiche.mode == "synthese", reponse.notes
    assert fiche.avertissements[0] == AVERTISSEMENT_SYNTHESE
    assert fiche.recette is not None
    (lavande,) = fiche.recette.huiles
    assert lavande.concentration_pct == 5  # 15 % dans la source, ramenée au plafond
    assert lavande.quantite.valeur == 0.5 and lavande.quantite.unite == "ml"
    assert lavande.sources == [web.URL_BLOG]
    assert any("dépasse le plafond" in n for n in reponse.notes)
    assert any("ramenée au plafond" in n for n in reponse.notes)
    assert any(b.startswith("🧪 Synthèse tracée") for b in fiche.badges)
    sure(reponse, d)


def test_synthese_n_invente_aucune_he() -> None:
    selection = {
        "huiles": [
            {"he_id": "cannelle_ecorce", "source": web.URL_BLOG},
            {"he_id": "lavande_vraie", "source": "https://invente.example"},
            {"he_id": "lavande_vraie", "source": web.URL_BLOG},
        ]
    }
    reponse = agent(web.llm_routeur(selection=selection), web.URL_BLOG).repondre(demande())
    assert reponse.fiche.recette is not None
    assert [h.he_id for h in reponse.fiche.recette.huiles] == ["lavande_vraie"]


def test_synthese_respecte_les_exclusions_personnelles() -> None:
    d = demande()
    a = agent(web.llm_routeur(selection=SELECTION_LAVANDE), web.URL_BLOG)
    reponse = a.repondre(d, exclusions_perso={"lavande_vraie"})
    assert reponse.fiche.mode == "aucune"
    assert reponse.fiche.recette is None
    assert any("exclusion personnelle" in n for n in reponse.notes)


def test_synthese_non_conforme_aucune_recette() -> None:
    d = demande(traitement=True)
    extraction = {
        "recettes": [
            {
                "nom_recette": "Baume",
                "voie": "cutanee",
                "huiles": [
                    {
                        "nom": "lavande vraie",
                        "quantite": {"valeur": 30, "unite": "gouttes"},
                        "source": web.URL_BLOG,
                    }
                ],
                "base_volume_ml": 10,
                "source": web.URL_BLOG,
            }
        ]
    }
    selection = {"huiles": [{"he_id": "lavande_vraie", "source": web.URL_BLOG}]}
    llm = web.llm_routeur(selection=selection, extraction=extraction)
    reponse = agent(llm, web.URL_BLOG).repondre(d, exclusions_perso={"lavande_vraie"})
    assert reponse.fiche.mode == "aucune"
    assert reponse.fiche.motif
    assert "Synthèse non conforme" in " ".join(reponse.notes)


def test_contradiction_signalee_et_valeur_restrictive() -> None:
    extraction = {
        "recettes": [web.recette_sommeil()],
        "indications": [
            {
                "nom": "lavande vraie",
                "type": "plafond",
                "valeur": 2,
                "unite": "%",
                "voie": "cutanée",
                "source": web.URL_SOMMEIL,
            }
        ],
    }
    selection = {
        "huiles": [
            {"he_id": "lavande_vraie", "source": web.URL_SOMMEIL},
            {"he_id": "orange_douce", "source": web.URL_SOMMEIL},
        ]
    }
    d = demande()
    llm = web.llm_routeur(selection=selection, extraction=extraction)
    reponse = agent(llm, web.URL_SOMMEIL).repondre(d)
    # La recette publiée (lavande 3 %) dépasse les 2 % indiqués : rejetée ⇒ synthèse,
    # où la valeur la plus restrictive (2 %) est retenue et la divergence signalée.
    assert any("rejetée" in n and "plafond de 2 %" in n for n in reponse.notes)
    fiche = reponse.fiche
    assert fiche.mode == "synthese", reponse.notes
    assert fiche.recette is not None
    lavande = next(h for h in fiche.recette.huiles if h.he_id == "lavande_vraie")
    assert lavande.concentration_pct == 2
    assert any("2 %" in c and "plus restrictive" in c for c in fiche.contradictions)
    sure(reponse, d)


def test_contradiction_entre_sources_en_synthese() -> None:
    sommeil = web.recette_sommeil()
    blog = web.recette_blog()
    sommeil["huiles"][0]["quantite"]["valeur"] = 12  # 6 % : rejetée verbatim
    extraction = {"recettes": [sommeil, blog]}
    pages = web.pages()
    pages[web.URL_SOMMEIL] = pages[web.URL_SOMMEIL].replace("6 gouttes", "12 gouttes")
    selection = {"huiles": [{"he_id": "lavande_vraie", "source": web.URL_SOMMEIL}]}
    a = agent(
        web.llm_routeur(selection=selection, extraction=extraction), web.URL_SOMMEIL, web.URL_BLOG
    )
    a.recuperateur = web.FakeRecuperateur(pages)
    reponse = a.repondre(demande())
    fiche = reponse.fiche
    assert fiche.mode == "synthese", reponse.notes
    assert any("divergentes" in c and "6 %" in c and "15 %" in c for c in fiche.contradictions)
    assert fiche.recette is not None
    assert fiche.recette.huiles[0].concentration_pct == 5


def test_aucune_recette_sure() -> None:
    reponse = agent(web.llm_routeur(), web.URL_BLOG).repondre(demande())
    assert reponse.fiche.mode == "aucune"
    assert "Aucune recette sûre" in (reponse.fiche.motif or "")


def test_analyse_llm_ne_fait_qu_ajouter_des_besoins() -> None:
    llm = web.llm_routeur(analyse={"besoins": ["stress", "inconnu"], "mots_cles": ["calme"]})
    corpus = [recette_corpus(id="stress", besoins=["stress"])]
    d = Demande(besoin="un mélange du soir", voies=["cutanee"], questionnaire=questionnaire())
    reponse = agent(llm, recherche=web.recherche(echouer=True), corpus=corpus).repondre(d)
    assert reponse.fiche.mode == "validee"


def test_journal_d_audit() -> None:
    audit = JournalAudit(connecter(":memory:"))
    agent(web.llm_routeur(), web.URL_SOMMEIL, audit=audit).repondre(demande())
    agent(web.llm_routeur(), audit=audit).repondre(demande(asthme=True))
    entrees = audit.lister()
    assert {e.mode for e in entrees} == {"publiee", "refus"}
    publiee = next(e for e in entrees if e.mode == "publiee")
    assert publiee.sources == [web.URL_SOMMEIL]
    refus = next(e for e in entrees if e.mode == "refus")
    assert refus.controles_declenches == ["profil_exclu"]
