"""Configuration de l'application, lue depuis l'environnement et le fichier `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Réglages de l'agent.

    Les clés d'API se lisent sous leur nom usuel (`MISTRAL_API_KEY`, `TAVILY_API_KEY`) ;
    les autres réglages sont préfixés par `AGENT_HE_`.
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENT_HE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Clés d'API (absentes tant que les connecteurs ne sont pas utilisés)
    mistral_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("MISTRAL_API_KEY", "AGENT_HE_MISTRAL_API_KEY"),
    )
    tavily_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("TAVILY_API_KEY", "AGENT_HE_TAVILY_API_KEY"),
    )
    mistral_model: str = "mistral-large-latest"

    # Emplacements locaux
    data_dir: Path = Path("data")
    db_path: Path = Path("data/agent_he.sqlite")
    chroma_dir: Path = Path("data/chroma")

    # Calcul des doses (spec §7) : nombre de gouttes par ml, affiché sur chaque fiche
    convention_gouttes_ml: int = Field(default=20, gt=0, le=100)

    # Priorité 1 : seuil de similarité pour retenir une recette existante (spec §6)
    seuil_correspondance: float = Field(default=0.8, ge=0.0, le=1.0)

    # Journal d'usage : seuils de proposition d'exclusion personnelle (spec §11.3)
    seuil_reactions_fortes: int = Field(default=1, ge=1)
    seuil_reactions_legeres: int = Field(default=2, ge=1)


@lru_cache
def get_settings() -> Settings:
    """Renvoie les réglages, chargés une seule fois par processus."""
    return Settings()
