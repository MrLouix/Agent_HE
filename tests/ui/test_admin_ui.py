"""Pages d'administration Streamlit, sur une copie des fichiers de données."""

import shutil
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from agent_he.admin import lire_boutiques, lire_securite
from agent_he.referentiel.securite import Statut, ecrire_entrees

from aides import DOSSIER_DONNEES, RACINE, entree

SCRIPT = str(RACINE / "app" / "streamlit_app.py")


@pytest.fixture
def dossier(tmp_path: Path) -> Path:
    for nom in ("boutiques.yaml", "huiles.yaml"):
        shutil.copy(DOSSIER_DONNEES / nom, tmp_path / nom)
    ecrire_entrees(tmp_path / "securite.yaml", [entree(statut="verifie", id="SEC-0001")])
    return tmp_path


def page(dossier: Path, fichier: str) -> AppTest:
    at = AppTest.from_file(SCRIPT, default_timeout=30)
    at.session_state["dossier_donnees"] = dossier
    return at.switch_page(f"app_pages/{fichier}").run()


def widget(liste: Any, libelle: str) -> Any:
    return next(w for w in liste if w.label == libelle)


def test_page_boutiques_affiche_tout_et_liens(dossier: Path) -> None:
    at = page(dossier, "boutiques.py")
    assert not at.exception
    assert [t.label for t in at.tabs] == [b.nom for b in lire_boutiques(dossier)]
    liens = {(b.label, b.url) for b in at.get("link_button")}
    assert ("robots.txt", "https://www.aroma-zone.com/robots.txt") in liens
    # Champs fixes en lecture seule : aucun widget de saisie pour l'url ou l'accès.
    assert all(w.label not in ("Site", "Accès", "Identifiant") for w in at.text_input)


def test_page_boutiques_enregistre_les_cgu(dossier: Path) -> None:
    at = page(dossier, "boutiques.py")
    widget(at.text_input, "Page des CGU").input("https://www.aroma-zone.com/cgv")
    widget(at.toggle, "CGU lues et compatibles").set_value(True)
    widget(at.text_input, "URL de recherche").input("https://www.aroma-zone.com/s?q={q}")
    widget(at.text_input, "Motif des liens produit (expression régulière)").input("/p/")
    widget(at.button, "Enregistrer").click()
    at.run()
    assert not at.exception
    boutique = next(b for b in lire_boutiques(dossier) if b.id == "aroma-zone")
    assert boutique.active and boutique.cgu_verifiees_le is not None
    assert "Tester la recherche « lavande »" in [b.label for b in at.get("link_button")]


def test_page_boutiques_refuse_une_saisie_invalide(dossier: Path) -> None:
    at = page(dossier, "boutiques.py")
    widget(at.text_input, "URL de recherche").input("https://www.aroma-zone.com/s")
    widget(at.button, "Enregistrer").click()
    at.run()
    assert "{q}" in at.error[0].value
    assert lire_boutiques(dossier)[0].url_recherche is None


def test_page_securite_cree_une_entree(dossier: Path) -> None:
    at = page(dossier, "securite.py")
    assert not at.exception
    assert any("Contrôles §9" in s.value for s in at.success)
    widget(at.selectbox, "Type").set_value("drapeau")
    widget(at.selectbox, "Huile essentielle").set_value("bergamote")
    widget(at.text_input, "Nom latin (tel qu'écrit dans la source)").input("Citrus bergamia")
    widget(at.selectbox, "Drapeau").set_value("phototoxique")
    widget(at.text_input, "Page").input("42")
    widget(at.text_input, "Localisation").input("test")
    widget(at.text_area, "Citation exacte (langue d'origine)").input("citation fictive")
    widget(at.button, "Créer l'entrée").click()
    at.run()
    assert not at.exception
    creee = next(e for e in lire_securite(dossier) if e.id == "SEC-0002")
    assert creee.drapeau == "phototoxique" and creee.source.page == 42
    assert at.selectbox(key="entree_choisie").value == "SEC-0002"


def test_page_securite_valide_une_entree_verifiee(dossier: Path) -> None:
    at = page(dossier, "securite.py")
    at.selectbox(key="entree_choisie").set_value("SEC-0001").run()
    assert not at.exception
    widget(at.button, "Valider").click()
    at.run()
    assert not at.exception
    assert lire_securite(dossier)[0].statut == Statut.VALIDE
