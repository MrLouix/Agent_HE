"""Le journal d'usage dans le pipeline (phase 7) : il ne peut que restreindre."""

from typing import Any

from agent_he.journal.repository import Journal
from agent_he.kb.embeddings import PlongeurLocal
from agent_he.kb.store import MagasinMemoire
from agent_he.models import Demande, EntreeUsage, ExclusionPerso
from agent_he.pipeline.agent import Agent, Reglages
from agent_he.search.reliability import charger_fiabilite
from agent_he.storage.db import connecter

import web
from aides import (
    DOSSIER_DONNEES,
    dose,
    questionnaire,
    recette,
    recette_corpus,
    referentiel,
    table_test,
)

SELECTION = {"huiles": [{"he_id": "lavande_vraie", "source": web.URL_BLOG}]}


def agent(journal: Journal, *urls: str, corpus: list[Any] | None = None, **kw: Any) -> Agent:
    magasin = MagasinMemoire(PlongeurLocal())
    magasin.indexer(corpus or [])
    return Agent(
        llm=kw.pop("llm", web.llm_routeur()),
        recherche=web.recherche(*urls),
        recuperateur=web.recuperateur(),
        table=table_test(),
        referentiel=referentiel(),
        fiabilite=charger_fiabilite(DOSSIER_DONNEES),
        reglages=Reglages(seuil_correspondance=kw.pop("seuil", 0.3), recherche_ouverte=True),
        magasin=magasin,
        corpus={r.id: r for r in corpus or []},
        journal=journal,
    )


def demande() -> Demande:
    return Demande(besoin="mieux dormir", voies=["cutanee"], questionnaire=questionnaire())


def journal() -> Journal:
    return Journal(connecter(":memory:"))


def test_dix_retours_parfaits_ne_relevent_pas_un_plafond() -> None:
    j = journal()
    for _ in range(10):
        entree = EntreeUsage(
            recette_ref="Huile de massage relaxante",
            voie="cutanee",
            efficacite=5,
            odeur=5,
            tolerance="aucune",
        )
        j.ajouter(entree, ["lavande_vraie"])
    reponse = agent(j, web.URL_BLOG).repondre(demande())
    assert reponse.fiche.mode == "aucune"
    assert any("dépasse le plafond" in n for n in reponse.notes)


def test_he_exclue_absente_de_toute_fiche_y_compris_synthese() -> None:
    j = journal()
    j.confirmer_exclusion(ExclusionPerso(he_id="lavande_vraie", motif="maux de tête"))
    llm = web.llm_routeur(selection=SELECTION)
    for urls, corpus in (((), [recette_corpus()]), ((web.URL_SOMMEIL,), []), ((web.URL_BLOG,), [])):
        reponse = agent(j, *urls, corpus=corpus, llm=llm).repondre(demande())
        recette_proposee = reponse.fiche.recette
        assert recette_proposee is None or all(
            h.he_id != "lavande_vraie" for h in recette_proposee.huiles
        )
    assert any("maux de tête" in n for n in reponse.notes)


def test_le_journal_n_est_jamais_une_source() -> None:
    j = journal()
    j.ajouter(
        EntreeUsage(
            recette_ref="roll-on-sommeil", voie="cutanee", efficacite=4, tolerance="legere"
        ),
        ["orange_douce"],
    )
    reponse = agent(j, corpus=[recette_corpus()]).repondre(demande())
    fiche = reponse.fiche
    assert fiche.mode == "validee"
    assert fiche.rappel_journal == "d'après ton journal : utilisée 1 fois, efficacité 4/5"
    assert any("Réaction légère" in a and "Orange douce" in a for a in fiche.avertissements)
    assert fiche.recette is not None
    toutes = {*fiche.recette.sources, *(s for h in fiche.recette.huiles for s in h.sources)}
    assert all(s.startswith("https://") for s in toutes)
    assert reponse.recette_ref == "roll-on-sommeil"


def test_classement_personnalise_parmi_les_recettes_conformes() -> None:
    j = journal()
    a = recette_corpus()
    b = recette_corpus(
        id="roll-on-orange",
        recette=recette(dose("orange_douce", 4), nom_recette="Roll-on sommeil orange").model_dump(),
    )
    sans_journal = agent(j, corpus=[a, b], seuil=0.1).repondre(demande())
    premiere = sans_journal.recette_ref
    autre = "roll-on-orange" if premiere == "roll-on-sommeil" else "roll-on-sommeil"
    huiles = {
        "roll-on-sommeil": ["lavande_vraie", "orange_douce"],
        "roll-on-orange": ["orange_douce"],
    }
    for _ in range(3):
        for ref, note in ((autre, 5), (premiere, 1)):
            entree = EntreeUsage(
                recette_ref=ref, voie="cutanee", efficacite=note, tolerance="aucune"
            )
            j.ajouter(entree, huiles[ref])
    avec_journal = agent(j, corpus=[a, b], seuil=0.1).repondre(demande())
    assert avec_journal.recette_ref == autre
