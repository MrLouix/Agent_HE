import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_he.cli import app
from agent_he.config import get_settings
from agent_he.kb.corpus import charger_corpus
from agent_he.kb.validation import FileValidation
from agent_he.models import Besoin, Confiance
from agent_he.storage.db import connecter

from aides import DOSSIER_DONNEES, dose, recette

runner = CliRunner()


@pytest.fixture
def dossier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    donnees = tmp_path / "data"
    shutil.copytree(DOSSIER_DONNEES, donnees)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_HE_DATA_DIR", str(donnees))
    monkeypatch.setenv("AGENT_HE_DB_PATH", str(donnees / "base.sqlite"))
    monkeypatch.setenv("AGENT_HE_CHROMA_DIR", str(donnees / "chroma"))
    get_settings.cache_clear()
    yield donnees
    get_settings.cache_clear()


def _candidate(dossier: Path) -> str:
    file = FileValidation(connecter(dossier / "base.sqlite"))
    r = recette(dose("lavande_vraie", 6), nom_recette="Roll-on test")
    return file.ajouter(r, [Besoin.SOMMEIL], Confiance.COMMERCIAL)


def test_reindex(dossier: Path) -> None:
    r = runner.invoke(app, ["corpus", "reindex"])
    assert r.exit_code == 0, r.output
    assert "recette(s) indexée(s)" in r.output


def test_candidates_valider(dossier: Path) -> None:
    assert "Aucune candidate" in runner.invoke(app, ["corpus", "candidates"]).output
    cid = _candidate(dossier)
    r = runner.invoke(app, ["corpus", "candidates"])
    assert cid in r.output
    assert "Roll-on test" in r.output
    r = runner.invoke(app, ["corpus", "valider", cid, "--besoin", "sommeil", "--besoin", "stress"])
    assert r.exit_code == 0, r.output
    assert "1 recette(s) indexée(s)" in r.output
    corpus = charger_corpus(dossier / "recettes")
    assert corpus["roll-on-test"].besoins == [Besoin.SOMMEIL, Besoin.STRESS]
    assert runner.invoke(app, ["corpus", "valider", cid]).exit_code == 1


def test_rejeter(dossier: Path) -> None:
    cid = _candidate(dossier)
    r = runner.invoke(app, ["corpus", "rejeter", cid, "--motif", "source douteuse"])
    assert r.exit_code == 0, r.output
    assert cid in runner.invoke(app, ["corpus", "candidates", "--toutes"]).output
    assert runner.invoke(app, ["corpus", "rejeter", "C0", "--motif", "x"]).exit_code == 1
