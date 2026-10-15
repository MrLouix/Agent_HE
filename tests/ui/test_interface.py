"""Interface Streamlit avec agent simulé (phase 6) : aucun appel réseau."""

from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from agent_he.interface import Services
from agent_he.kb.validation import FileValidation
from agent_he.models import AVERTISSEMENT_SYNTHESE, TrancheAge, Voie
from agent_he.pipeline.agent import Agent, Reglages
from agent_he.safety.keywords import charger_filet
from agent_he.search.reliability import charger_fiabilite
from agent_he.storage.db import connecter
from agent_he.storage.favorites import Favoris, Historique

import web
from aides import DOSSIER_DONNEES, RACINE, referentiel, table_test

SCRIPT = str(RACINE / "app" / "streamlit_app.py")
SELECTION = {"huiles": [{"he_id": "lavande_vraie", "source": web.URL_BLOG}]}


def services(*urls: str, agent: bool = True) -> Services:
    connexion = connecter(":memory:")
    fake = Agent(
        llm=web.llm_routeur(selection=SELECTION),
        recherche=web.recherche(*urls),
        recuperateur=web.recuperateur(),
        table=table_test(),
        referentiel=referentiel(),
        fiabilite=charger_fiabilite(DOSSIER_DONNEES),
        reglages=Reglages(recherche_ouverte=True),
    )
    return Services(
        agent=fake if agent else None,
        historique=Historique(connexion),
        favoris=Favoris(connexion),
        file_validation=FileValidation(connexion),
        filet=charger_filet(DOSSIER_DONNEES),
        erreur=None if agent else "Clés d'API absentes : renseigne MISTRAL_API_KEY.",
    )


def app(svc: Services) -> AppTest:
    at = AppTest.from_file(SCRIPT, default_timeout=30)
    at.session_state["services"] = svc
    return at.run()


def remplir(
    at: AppTest,
    besoin: str = "mieux dormir",
    age: TrancheAge | None = TrancheAge.ADULTE,
    **cases: bool,
) -> AppTest:
    at.text_input(key="besoin").input(besoin)
    at.multiselect(key="voies").select(Voie.CUTANEE)
    if age is not None:
        at.selectbox(key="age").select(age)
    for cle, valeur in cases.items():
        at.checkbox(key=cle).set_value(valeur)
    return at.run()


def rechercher(at: AppTest) -> AppTest:
    return at.button(key="rechercher").click().run()


def textes(at: AppTest) -> str:
    morceaux: list[Any] = [*at.markdown, *at.warning, *at.error, *at.info, *at.caption, *at.success]
    return "\n".join(str(m.value) for m in morceaux)


def test_bandeau_permanent() -> None:
    at = app(services())
    assert not at.exception
    assert any("pas un avis médical" in w.value for w in at.warning)


def test_recherche_bloquee_sans_questionnaire() -> None:
    svc = services(web.URL_SOMMEIL)
    at = remplir(app(svc), age=None)
    at = rechercher(at)
    assert any("Recherche bloquée" in e.value and "âge" in e.value for e in at.error)
    assert "reponse" not in at.session_state
    assert svc.historique.lister() == []


def test_fiche_publiee_et_historique() -> None:
    svc = services(web.URL_SOMMEIL)
    at = rechercher(remplir(app(svc)))
    assert not at.exception
    contenu = textes(at)
    assert "Roll-on sommeil apaisant" in contenu
    assert "20 gouttes/ml" in contenu
    assert len(svc.historique.lister()) == 1
    at = at.button(key="favori").click().run()
    assert [f.nom for f in svc.favoris.lister()] == ["Roll-on sommeil apaisant"]


def test_avertissement_visible_en_synthese() -> None:
    at = rechercher(remplir(app(services(web.URL_BLOG))))
    assert not at.exception
    assert at.session_state["reponse"].fiche.mode == "synthese"
    # Streamlit affiche l'emoji initial comme icône : on compare le texte sans lui.
    texte = AVERTISSEMENT_SYNTHESE.removeprefix("⚠️").strip()
    assert any(texte in w.value for w in at.warning)


def test_refus_explicatif_grossesse() -> None:
    at = rechercher(remplir(app(services(web.URL_SOMMEIL)), grossesse_allaitement=True))
    assert not at.exception
    erreurs = " ".join(e.value for e in at.error)
    assert "Aucun dosage proposé" in erreurs
    assert "Grossesse" in erreurs
    assert "sauge_officinale" in textes(at)
    assert any("professionnel" in i.value for i in at.info)


def test_risque_dans_le_texte_demande_confirmation() -> None:
    svc = services(web.URL_SOMMEIL)
    at = remplir(app(svc), besoin="dormir, je suis enceinte")
    assert any("risque non coché" in w.value for w in at.warning)
    at = rechercher(at)
    assert any("confirme le questionnaire" in e.value for e in at.error)
    at.checkbox(key="confirmation").check()
    at = rechercher(at.run())
    assert "reponse" in at.session_state


def test_cle_api_absente_message_clair() -> None:
    at = rechercher(remplir(app(services(agent=False))))
    assert any("Clés d'API absentes" in e.value for e in at.error)
    assert any("l'agent n'est pas configuré" in e.value for e in at.error)


@pytest.mark.parametrize("onglet", ["Historique", "Favoris", "File de validation"])
def test_onglets_presents(onglet: str) -> None:
    at = app(services())
    assert onglet in [t.label for t in at.tabs]
