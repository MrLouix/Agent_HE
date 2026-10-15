"""Indexation du corpus validé."""

from pathlib import Path

from agent_he.kb.corpus import RecetteCorpus, charger_corpus
from agent_he.kb.store import Magasin


def reindexer(dossier_recettes: Path, magasin: Magasin) -> dict[str, RecetteCorpus]:
    """Recharge le corpus depuis le disque et reconstruit l'index ; renvoie le corpus."""
    corpus = charger_corpus(dossier_recettes)
    magasin.indexer(corpus.values())
    return corpus


def charger_et_indexer_si_besoin(
    dossier_recettes: Path, magasin: Magasin
) -> dict[str, RecetteCorpus]:
    """Charge le corpus ; ne reconstruit l'index que s'il ne correspond plus au disque."""
    corpus = charger_corpus(dossier_recettes)
    if magasin.ids() != set(corpus):
        magasin.indexer(corpus.values())
    return corpus
