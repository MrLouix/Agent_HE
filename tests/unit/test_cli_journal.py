import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_he.cli import app
from agent_he.config import get_settings
from agent_he.journal.repository import Journal
from agent_he.storage.db import connecter

from aides import DOSSIER_DONNEES

runner = CliRunner()


@pytest.fixture
def base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    donnees = tmp_path / "data"
    shutil.copytree(DOSSIER_DONNEES, donnees)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_HE_DATA_DIR", str(donnees))
    monkeypatch.setenv("AGENT_HE_DB_PATH", str(tmp_path / "base.sqlite"))
    get_settings.cache_clear()
    yield tmp_path / "base.sqlite"
    get_settings.cache_clear()


def test_ajout_melange_libre_et_proposition(base: Path) -> None:
    r = runner.invoke(
        app,
        [
            "journal",
            "add",
            "--melange",
            "cannelle:1:gouttes",
            "--voie",
            "cutanee",
            "--tolerance",
            "forte",
            "--reaction",
            "brûlure",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "Proposition : exclure cannelle_ecorce" in r.output
    assert Journal(connecter(base)).exclusions() == {}
    assert runner.invoke(app, ["journal", "exclure", "cannelle_ecorce"]).exit_code == 0
    assert "cannelle_ecorce" in Journal(connecter(base)).exclusions()
    assert "cannelle_ecorce" in runner.invoke(app, ["journal", "exclusions"]).output
    assert runner.invoke(app, ["journal", "retirer", "cannelle_ecorce"]).exit_code == 0
    assert Journal(connecter(base)).exclusions() == {}


def test_ajout_recette_avec_he(base: Path) -> None:
    args = ["journal", "add", "--recette", "roll-on", "--voie", "cutanee", "--tolerance", "aucune"]
    r = runner.invoke(app, args)
    assert r.exit_code == 1  # HE introuvables pour cette référence
    r = runner.invoke(app, [*args, "--he", "lavande_vraie", "--efficacite", "4"])
    assert r.exit_code == 0, r.output
    assert "roll-on" in runner.invoke(app, ["journal", "list"]).output


def test_options_exclusives(base: Path) -> None:
    r = runner.invoke(app, ["journal", "add", "--voie", "bain", "--tolerance", "aucune"])
    assert r.exit_code == 1
    assert runner.invoke(app, ["journal", "exclure", "licorne"]).exit_code == 1
