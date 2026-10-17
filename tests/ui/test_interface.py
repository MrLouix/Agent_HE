"""Interface Streamlit avec agent simulé (phase 6) : aucun appel réseau."""

from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from agent_he.interface import Services
from agent_he.journal.repository import Journal
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
        journal=Journal(connexion),
        referentiel=referentiel(),
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
    at.pills(key="voies").select(Voie.CUTANEE)
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
    assert any(e.proto.title == "Aucun dosage proposé" for e in at.error)
    erreurs = " ".join(e.value for e in at.error)
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
    assert any(t.label.endswith(onglet) for t in at.tabs)


def test_j_ai_utilise_cette_recette() -> None:
    svc = services(web.URL_SOMMEIL)
    at = rechercher(remplir(app(svc)))
    at.segmented_control(key="tol-fiche").set_value("legere")
    at.text_input(key="reac-fiche").input("rougeurs")
    at = at.button(key="FormSubmitter:usage-fiche-Enregistrer le retour").click().run()
    assert not at.exception
    ((entree, huiles),) = svc.journal.lister()
    assert entree.recette_ref == "Roll-on sommeil apaisant"
    assert entree.tolerance == "legere"
    assert huiles == ["lavande_vraie", "orange_douce"]


def test_proposition_puis_confirmation_d_exclusion() -> None:
    from agent_he.models import EntreeUsage

    svc = services()
    svc.journal.ajouter(
        EntreeUsage(recette_ref="r", voie="cutanee", tolerance="forte"), ["cannelle_ecorce"]
    )
    at = app(svc)
    assert any("Proposition : exclure Cannelle de Ceylan" in w.value for w in at.warning)
    assert svc.journal.exclusions() == {}
    at = at.button(key="exclure-cannelle_ecorce").click().run()
    assert "cannelle_ecorce" in svc.journal.exclusions()
    assert any(":material/block: **Cannelle de Ceylan**" in m.value for m in at.markdown)


def test_onglet_produits_sans_boutique_active() -> None:
    at = app(services())
    assert any("Aucune boutique active" in c.value for c in at.caption)


def test_onglet_produits_compare_les_he_de_la_fiche(tmp_path: Any) -> None:
    import httpx

    from agent_he.products.compare import Comparateur
    from agent_he.products.scraper import Scraper

    from aides import boutique, fixture

    pages = {
        "https://www.aroma-zone.com/recherche?q=Lavande+vraie": fixture("recherche.html"),
        "https://www.aroma-zone.com/produit/lavande-vraie": fixture("aroma-zone.html"),
    }

    def repondre(requete: httpx.Request) -> httpx.Response:
        if requete.url.path == "/robots.txt":
            return httpx.Response(200, text="")
        texte = pages.get(str(requete.url))
        return httpx.Response(200, text=texte) if texte else httpx.Response(404)

    scraper = Scraper(
        tmp_path, httpx.Client(transport=httpx.MockTransport(repondre)), attendre=lambda d: None
    )
    svc = services(web.URL_SOMMEIL)
    svc.comparateur = Comparateur([boutique()], scraper, referentiel())
    at = rechercher(remplir(app(svc)))
    at = at.button(key="comparer").click().run()
    assert not at.exception
    assert any("Lavandula angustifolia — linalol" in m.value for m in at.markdown)
