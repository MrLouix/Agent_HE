"""Assemblage des services réels (Mistral, Tavily, Chroma, SQLite) à partir des réglages."""

from agent_he.config import Settings
from agent_he.kb.embeddings import Plongeur, PlongeurLocal, PlongeurMistral
from agent_he.kb.ingest import charger_et_indexer_si_besoin
from agent_he.kb.store import Magasin, MagasinChroma
from agent_he.kb.validation import FileValidation
from agent_he.pipeline.agent import Agent, Reglages
from agent_he.referentiel.huiles import charger_referentiel
from agent_he.referentiel.securite import charger_table
from agent_he.storage.audit import JournalAudit
from agent_he.storage.db import connecter


class ErreurConfiguration(RuntimeError):
    """Configuration incomplète (clé d'API absente…), avec un message pour l'utilisateur."""


def construire_magasin(reglages: Settings) -> Magasin:
    plongeur: Plongeur = PlongeurLocal()
    if reglages.plongeur == "mistral":
        if reglages.mistral_api_key is None:
            raise ErreurConfiguration("AGENT_HE_PLONGEUR=mistral exige MISTRAL_API_KEY.")
        plongeur = PlongeurMistral(reglages.mistral_api_key.get_secret_value())
    return MagasinChroma(reglages.chroma_dir, plongeur)


def file_validation(reglages: Settings) -> FileValidation:
    return FileValidation(connecter(reglages.db_path))


def reglages_agent(reglages: Settings) -> Reglages:
    return Reglages(
        convention_gouttes_ml=reglages.convention_gouttes_ml,
        recherche_ouverte=reglages.recherche_ouverte,
        max_resultats=reglages.max_resultats,
        seuil_correspondance=reglages.seuil_correspondance,
    )


def construire_agent(reglages: Settings) -> Agent:
    """Agent branché sur les vrais services ; lève `ErreurConfiguration` si clé absente."""
    from agent_he.llm.mistral import MistralLLM
    from agent_he.search.fetch import RecuperateurHttp
    from agent_he.search.reliability import charger_fiabilite
    from agent_he.search.tavily import TavilySearch

    if reglages.mistral_api_key is None or reglages.tavily_api_key is None:
        raise ErreurConfiguration(
            "Clés d'API absentes : renseigne MISTRAL_API_KEY et TAVILY_API_KEY dans .env "
            "(voir .env.example)."
        )
    dossier = reglages.data_dir
    magasin = construire_magasin(reglages)
    return Agent(
        llm=MistralLLM(reglages.mistral_api_key.get_secret_value(), reglages.mistral_model),
        recherche=TavilySearch(reglages.tavily_api_key.get_secret_value()),
        recuperateur=RecuperateurHttp(),
        table=charger_table(dossier),
        referentiel=charger_referentiel(dossier),
        fiabilite=charger_fiabilite(dossier),
        reglages=reglages_agent(reglages),
        magasin=magasin,
        corpus=charger_et_indexer_si_besoin(dossier / "recettes", magasin),
        file_validation=file_validation(reglages),
        audit=JournalAudit(connecter(reglages.db_path)),
    )
