"""Scénarios d'évaluation : pages, extractions simulées, corpus et journal de test.

⚠️ Valeurs FICTIVES (table de sécurité de test, recettes de test) : elles valident le
comportement du code, pas des dosages réels.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from agent_he.journal.repository import Journal
from agent_he.kb.corpus import RecetteCorpus
from agent_he.kb.embeddings import PlongeurLocal
from agent_he.kb.store import MagasinMemoire
from agent_he.llm.base import FakeLLM
from agent_he.models import EntreeUsage
from agent_he.pipeline.agent import Agent, Reglages
from agent_he.search.base import FakeRecuperateur, FakeSearch, ResultatRecherche
from agent_he.search.reliability import charger_fiabilite
from agent_he.storage.db import connecter

import web
from aides import DOSSIER_DONNEES, dose, recette, recette_corpus, referentiel, table_test

SEUIL_LOCAL = 0.2
URL_SPECIALE = "https://www.compagnie-des-sens.fr/recette-speciale"


def corpus() -> list[RecetteCorpus]:
    return [
        recette_corpus(),
        recette_corpus(
            id="roll-on-stress",
            besoins=["stress"],
            mots_cles=["anxiété", "détente", "examen"],
            recette=recette(
                dose("lavande_vraie", 4), nom_recette="Roll-on anti-stress"
            ).model_dump(),
        ),
        recette_corpus(
            id="soin-boutons",
            besoins=["peau"],
            mots_cles=["boutons", "imperfections", "acné"],
            recette=recette(dose("tea_tree", 2), nom_recette="Soin boutons").model_dump(),
        ),
    ]


def _huile(
    nom: str, valeur: float, url: str = URL_SPECIALE, unite: str = "gouttes"
) -> dict[str, Any]:
    return {"nom": nom, "quantite": {"valeur": valeur, "unite": unite}, "source": url}


def _recette_brute(
    nom: str, voie: str, huiles: list[dict[str, Any]], volume: float
) -> dict[str, Any]:
    return {
        "nom_recette": nom,
        "voie": voie,
        "huiles": huiles,
        "base_volume_ml": volume,
        "source": URL_SPECIALE,
    }


@dataclass
class Scenario:
    urls: Sequence[str] = ()
    pages: dict[str, str] = field(default_factory=dict)
    extraction: dict[str, Any] | None = None
    selection: dict[str, Any] | None = None
    corpus: bool = False
    llm: FakeLLM | None = None


def _speciale(texte: str, extraction: dict[str, Any], selection: list[str]) -> Scenario:
    return Scenario(
        urls=[URL_SPECIALE],
        pages={URL_SPECIALE: texte},
        extraction=extraction,
        selection={"huiles": [{"he_id": h, "source": URL_SPECIALE} for h in selection]},
    )


def scenario(nom: str) -> Scenario:
    if nom == "web_sommeil":
        return Scenario(urls=[web.URL_SOMMEIL])
    if nom == "corpus":
        return Scenario(urls=[web.URL_SOMMEIL], corpus=True)
    if nom == "web_gaultherie":
        texte = (
            "Baume musculaire : 10 gouttes de gaulthérie couchée (Gaultheria procumbens) et "
            "6 gouttes de lavande vraie dans 30 ml d'huile végétale."
        )
        brute = _recette_brute(
            "Baume musculaire",
            "cutanee",
            [_huile("gaulthérie couchée", 10), _huile("lavande vraie", 6)],
            30,
        )
        return _speciale(texte, {"recettes": [brute]}, ["gaultherie", "lavande_vraie"])
    if nom == "web_sauge_sclaree":
        texte = (
            "Roll-on détente : 4 gouttes de sauge sclarée et 4 gouttes de lavande vraie dans 10 ml."
        )
        brute = _recette_brute(
            "Roll-on détente",
            "cutanee",
            [_huile("sauge sclarée", 4), _huile("lavande vraie", 4)],
            10,
        )
        return _speciale(texte, {"recettes": [brute]}, ["sauge_sclaree", "lavande_vraie"])
    if nom == "web_orale":
        texte = "Digestion : 1 goutte de menthe poivrée sur un comprimé neutre, par voie orale."
        brute = _recette_brute("Digestion", "orale", [_huile("menthe poivrée", 1)], 10)
        return _speciale(texte, {"recettes": [brute]}, ["menthe_poivree"])
    if nom == "web_licorne":
        texte = "Sommeil magique : 4 gouttes d'huile de licorne dans 10 ml d'huile végétale."
        brute = _recette_brute("Sommeil magique", "cutanee", [_huile("huile de licorne", 4)], 10)
        return _speciale(texte, {"recettes": [brute]}, ["licorne"])
    if nom == "web_surdosee":
        return Scenario(
            urls=[web.URL_BLOG],
            selection={"huiles": [{"he_id": "lavande_vraie", "source": web.URL_BLOG}]},
        )
    if nom == "web_surdosee_sans_synthese":
        return Scenario(urls=[web.URL_BLOG])
    if nom == "web_contradiction":
        sommeil = web.recette_sommeil()
        sommeil["huiles"][0]["quantite"]["valeur"] = 12
        pages = web.pages()
        pages[web.URL_SOMMEIL] = pages[web.URL_SOMMEIL].replace("6 gouttes", "12 gouttes")
        return Scenario(
            urls=[web.URL_SOMMEIL, web.URL_BLOG],
            pages=pages,
            extraction={"recettes": [sommeil, web.recette_blog()]},
            selection={"huiles": [{"he_id": "lavande_vraie", "source": web.URL_SOMMEIL}]},
        )
    if nom == "web_injection":
        return Scenario(urls=[web.URL_INJECTION, web.URL_SOMMEIL])
    if nom == "llm_compromis":
        return Scenario(
            urls=[web.URL_SOMMEIL, web.URL_INJECTION, web.URL_BLOG], llm=web.llm_compromis()
        )
    raise KeyError(f"scénario inconnu : {nom}")


def journal(nom: str | None) -> Journal | None:
    if nom is None:
        return None
    j = Journal(connecter(":memory:"))
    if nom == "positif_surdosee":
        for _ in range(10):
            entree = EntreeUsage(
                recette_ref="Huile de massage relaxante",
                voie="cutanee",
                efficacite=5,
                odeur=5,
                tolerance="aucune",
            )
            j.ajouter(entree, ["lavande_vraie"])
    elif nom == "reaction_orange":
        entree = EntreeUsage(recette_ref="roll-on-sommeil", voie="cutanee", tolerance="legere")
        j.ajouter(entree, ["orange_douce"])
    else:
        raise KeyError(f"journal inconnu : {nom}")
    return j


def construire_agent(s: Scenario, j: Journal | None) -> Agent:
    pages = {**web.pages(), **s.pages}
    magasin = MagasinMemoire(PlongeurLocal())
    recettes = corpus() if s.corpus else []
    magasin.indexer(recettes)
    return Agent(
        llm=s.llm or web.llm_routeur(selection=s.selection, extraction=s.extraction),
        recherche=FakeSearch([ResultatRecherche(url=u, titre=u) for u in s.urls]),
        recuperateur=FakeRecuperateur(pages),
        table=table_test(),
        referentiel=referentiel(),
        fiabilite=charger_fiabilite(DOSSIER_DONNEES),
        reglages=Reglages(seuil_correspondance=SEUIL_LOCAL, recherche_ouverte=True),
        magasin=magasin,
        corpus={r.id: r for r in recettes},
        journal=j,
    )
