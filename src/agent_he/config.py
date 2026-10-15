"""Configuration de l'application, lue depuis l'environnement et le fichier `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
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

    @field_validator("mistral_api_key", "tavily_api_key", mode="before")
    @classmethod
    def _cle_vide_absente(cls, valeur: object) -> object:
        """`MISTRAL_API_KEY=` (copie brute de .env.example) vaut « clé absente »."""
        if isinstance(valeur, str) and not valeur.strip():
            return None
        return valeur

    # Personne qui utilise l'outil (traçabilité des vérifications et validations)
    utilisateur: str = "moi"

    # Emplacements locaux
    data_dir: Path = Path("data")
    db_path: Path = Path("data/agent_he.sqlite")
    chroma_dir: Path = Path("data/chroma")

    # Calcul des doses (spec §7) : nombre de gouttes par ml, affiché sur chaque fiche
    convention_gouttes_ml: int = Field(default=20, gt=0, le=100)

    # Recherche web : liste blanche, puis passage ouvert optionnel (sources « non vérifié »)
    recherche_ouverte: bool = False
    max_resultats: int = Field(default=5, ge=1, le=20)

    # Plongements pour l'index du corpus : « local » (hors ligne) ou « mistral »
    plongeur: Literal["local", "mistral"] = "local"

    # Priorité 1 : seuil de similarité pour retenir une recette existante (spec §6).
    # Non renseigné : valeur calibrée pour le plongeur choisi (kb/calibrage.py).
    seuil_correspondance: float | None = Field(default=None, ge=0.0, le=1.0)

    @property
    def seuil_correspondance_effectif(self) -> float:
        from agent_he.kb.calibrage import seuil_par_defaut

        if self.seuil_correspondance is not None:
            return self.seuil_correspondance
        return seuil_par_defaut(self.plongeur)

    # Journal d'usage : seuils de proposition d'exclusion personnelle (spec §11.3)
    seuil_reactions_fortes: int = Field(default=1, ge=1)
    seuil_reactions_legeres: int = Field(default=2, ge=1)


@lru_cache
def get_settings() -> Settings:
    """Renvoie les réglages, chargés une seule fois par processus."""
    return Settings()
