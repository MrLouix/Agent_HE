from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import agent_he.cli as cli
from agent_he.config import Settings, get_settings
from agent_he.pipeline.agent import Agent
from agent_he.search.reliability import charger_fiabilite

import web
from aides import DOSSIER_DONNEES, referentiel, table_test

runner = CliRunner()


@pytest.fixture(autouse=True)
def _agent_simule(monkeypatch: pytest.MonkeyPatch) -> None:
    def construire(_reglages: Settings) -> Agent:
        return Agent(
            llm=web.llm_fidele(),
            recherche=web.recherche(),
            recuperateur=web.recuperateur(),
            table=table_test(),
            referentiel=referentiel(),
            fiabilite=charger_fiabilite(DOSSIER_DONNEES),
        )

    monkeypatch.setattr(cli, "construire_agent", construire)
    monkeypatch.setenv("AGENT_HE_DATA_DIR", str(DOSSIER_DONNEES))
    get_settings.cache_clear()


def test_ask_affiche_la_fiche() -> None:
    r = runner.invoke(cli.app, ["ask", "mieux dormir", "--voie", "cutanee", "--age", "adulte"])
    assert r.exit_code == 0, r.output
    assert "Roll-on sommeil apaisant" in r.output
    assert "Recette publiée" in r.output
    assert "20 gouttes/ml" in r.output
    assert "| Lavande vraie | *Lavandula angustifolia* | — | 3 % | 0,3 | 6 |" in r.output


def test_ask_refus_grossesse() -> None:
    r = runner.invoke(
        cli.app, ["ask", "dormir", "--voie", "cutanee", "--age", "adulte", "--grossesse"]
    )
    assert r.exit_code == 0
    assert "Aucun dosage proposé" in r.output
    assert "sauge_officinale" in r.output


def test_ask_questionnaire_obligatoire() -> None:
    assert runner.invoke(cli.app, ["ask", "dormir", "--voie", "cutanee"]).exit_code != 0


def test_ask_voie_orale_refusee() -> None:
    r = runner.invoke(cli.app, ["ask", "digestion", "--voie", "orale", "--age", "adulte"])
    assert r.exit_code != 0


def test_ask_risque_non_coche_demande_confirmation() -> None:
    args = ["ask", "dormir", "--voie", "cutanee", "--age", "adulte", "--texte", "je suis enceinte"]
    r = runner.invoke(cli.app, args)
    assert r.exit_code == 1
    assert "grossesse" in r.output
    assert runner.invoke(cli.app, [*args, "--confirme"]).exit_code == 0


def test_cles_absentes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.undo()
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(typer.Exit):
        cli.construire_agent(Settings())
