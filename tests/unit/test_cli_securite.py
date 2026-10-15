import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_he.cli import app
from agent_he.config import get_settings
from agent_he.referentiel.securite import Statut, ecrire_entrees, lire_entrees

from aides import DOSSIER_DONNEES, drapeau, entree, plafond

runner = CliRunner()


@pytest.fixture
def dossier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    donnees = tmp_path / "data"
    donnees.mkdir()
    shutil.copy(DOSSIER_DONNEES / "huiles.yaml", donnees / "huiles.yaml")
    ecrire_entrees(
        donnees / "securite.yaml",
        [entree(statut="brouillon", id="SEC-0001"), drapeau("bergamote", "phototoxique")],
        entete="# Table de test\n",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_HE_DATA_DIR", str(donnees))
    get_settings.cache_clear()
    yield donnees
    get_settings.cache_clear()


def _statut(dossier: Path, entree_id: str) -> Statut:
    return next(e for e in lire_entrees(dossier / "securite.yaml") if e.id == entree_id).statut


def test_verifier_puis_valider(dossier: Path) -> None:
    r = runner.invoke(app, ["securite", "verifier", "SEC-0001", "--conforme", "--par", "relecteur"])
    assert r.exit_code == 0, r.output
    assert _statut(dossier, "SEC-0001") == Statut.VERIFIE
    r = runner.invoke(app, ["securite", "valider", "SEC-0001"])
    assert r.exit_code == 0, r.output
    assert _statut(dossier, "SEC-0001") == Statut.VALIDE
    assert (dossier / "securite.yaml").read_text(encoding="utf-8").startswith("# Table de test")
    assert runner.invoke(app, ["securite", "controler"]).exit_code == 0


def test_non_conforme(dossier: Path) -> None:
    r = runner.invoke(
        app,
        ["securite", "verifier", "SEC-0001", "--non-conforme", "page fausse", "--par", "r"],
    )
    assert r.exit_code == 0, r.output
    assert _statut(dossier, "SEC-0001") == Statut.BROUILLON
    assert runner.invoke(app, ["securite", "valider", "SEC-0001"]).exit_code == 1


def test_options_exclusives(dossier: Path) -> None:
    assert runner.invoke(app, ["securite", "verifier", "SEC-0001"]).exit_code == 1
    r = runner.invoke(
        app, ["securite", "verifier", "SEC-0001", "--conforme", "--non-conforme", "x"]
    )
    assert r.exit_code == 1


def test_entree_introuvable(dossier: Path) -> None:
    r = runner.invoke(app, ["securite", "valider", "SEC-9999"])
    assert r.exit_code == 1
    assert "introuvable" in r.output


def test_controler_detecte_un_probleme(dossier: Path) -> None:
    e = plafond("lavande_vraie", 5)
    e.valeur = 40
    ecrire_entrees(dossier / "securite.yaml", [e])
    r = runner.invoke(app, ["securite", "controler"])
    assert r.exit_code == 1
    assert "empreinte" in r.output


def test_rapport(dossier: Path, tmp_path: Path) -> None:
    sortie = tmp_path / "audit.md"
    r = runner.invoke(app, ["securite", "rapport", "--sortie", str(sortie)])
    assert r.exit_code == 0, r.output
    assert "Audit de la table de sécurité" in sortie.read_text(encoding="utf-8")
    r = runner.invoke(app, ["securite", "rapport"])
    assert r.exit_code == 0
    assert list((tmp_path / "docs" / "audit").glob("securite-*.md"))
