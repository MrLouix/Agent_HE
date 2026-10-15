from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_he.config import Settings


@pytest.fixture(autouse=True)
def _environnement_propre(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Isole les tests d'un éventuel .env local et des variables du poste.
    monkeypatch.chdir(tmp_path)
    for nom in ("MISTRAL_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.delenv(nom, raising=False)


def test_valeurs_par_defaut() -> None:
    reglages = Settings()
    assert reglages.mistral_api_key is None
    assert reglages.convention_gouttes_ml == 20
    assert reglages.seuil_correspondance == 0.8
    assert reglages.seuil_reactions_fortes == 1
    assert reglages.seuil_reactions_legeres == 2


def test_cles_api_lues_sous_leur_nom_usuel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "cle-mistral")
    monkeypatch.setenv("TAVILY_API_KEY", "cle-tavily")
    reglages = Settings()
    assert reglages.mistral_api_key is not None
    assert reglages.mistral_api_key.get_secret_value() == "cle-mistral"
    assert reglages.tavily_api_key is not None
    assert reglages.tavily_api_key.get_secret_value() == "cle-tavily"


def test_cle_api_masquee_dans_les_affichages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "cle-secrete")
    assert "cle-secrete" not in repr(Settings())


def test_reglages_prefixes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HE_CONVENTION_GOUTTES_ML", "25")
    monkeypatch.setenv("AGENT_HE_SEUIL_CORRESPONDANCE", "0.9")
    reglages = Settings()
    assert reglages.convention_gouttes_ml == 25
    assert reglages.seuil_correspondance == 0.9


def test_lecture_du_fichier_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("TAVILY_API_KEY=depuis-fichier\n", encoding="utf-8")
    reglages = Settings()
    assert reglages.tavily_api_key is not None
    assert reglages.tavily_api_key.get_secret_value() == "depuis-fichier"


@pytest.mark.parametrize(
    ("variable", "valeur"),
    [
        ("AGENT_HE_CONVENTION_GOUTTES_ML", "0"),
        ("AGENT_HE_SEUIL_CORRESPONDANCE", "1.5"),
        ("AGENT_HE_SEUIL_REACTIONS_LEGERES", "0"),
    ],
)
def test_reglages_hors_bornes_refuses(
    monkeypatch: pytest.MonkeyPatch, variable: str, valeur: str
) -> None:
    monkeypatch.setenv(variable, valeur)
    with pytest.raises(ValidationError):
        Settings()
