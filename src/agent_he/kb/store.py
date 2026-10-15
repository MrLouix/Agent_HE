"""Index vectoriel du corpus validé : Chroma (persistant) ou mémoire (tests)."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from agent_he.kb.corpus import RecetteCorpus
from agent_he.kb.embeddings import Plongeur, cosinus
from agent_he.models import Besoin, Voie

COLLECTION = "recettes-validees"


class ErreurIndex(RuntimeError):
    """L'index est inutilisable (à reconstruire avec `agent-he corpus reindex`)."""


@dataclass(frozen=True)
class Correspondance:
    id: str
    similarite: float
    """Similarité cosinus, de 0 (sans rapport) à 1 (identique)."""


class Magasin(Protocol):
    def ids(self) -> set[str]:
        """Identifiants des recettes indexées."""
        ...

    def indexer(self, recettes: Iterable[RecetteCorpus]) -> int:
        """Remplace l'index par ces recettes ; renvoie le nombre de recettes indexées."""
        ...

    def chercher(
        self, texte: str, voies: Sequence[Voie], besoins: Sequence[Besoin], n: int = 5
    ) -> list[Correspondance]:
        """Recettes de l'une des voies et de l'un des besoins, par similarité décroissante."""
        ...


def _metadonnees(recette: RecetteCorpus) -> dict[str, str | bool]:
    meta: dict[str, str | bool] = {
        "voie": str(recette.recette.voie),
        "confiance": str(recette.confiance),
        "sources": " ".join(recette.recette.sources),
    }
    for besoin in recette.besoins:
        meta[f"besoin_{besoin}"] = True
    return meta


class MagasinMemoire:
    def __init__(self, plongeur: Plongeur) -> None:
        self._plongeur = plongeur
        self._entrees: list[tuple[RecetteCorpus, list[float]]] = []

    def ids(self) -> set[str]:
        return {r.id for r, _ in self._entrees}

    def indexer(self, recettes: Iterable[RecetteCorpus]) -> int:
        liste = list(recettes)
        vecteurs = self._plongeur.plonger([r.texte_index() for r in liste])
        self._entrees = list(zip(liste, vecteurs, strict=True))
        return len(liste)

    def chercher(
        self, texte: str, voies: Sequence[Voie], besoins: Sequence[Besoin], n: int = 5
    ) -> list[Correspondance]:
        if not besoins or not voies:
            return []
        (requete,) = self._plongeur.plonger([texte])
        resultats = [
            Correspondance(r.id, cosinus(requete, v))
            for r, v in self._entrees
            if r.recette.voie in voies and set(r.besoins) & set(besoins)
        ]
        return sorted(resultats, key=lambda c: c.similarite, reverse=True)[:n]


class MagasinChroma:
    def __init__(self, dossier: Path, plongeur: Plongeur) -> None:
        import chromadb
        from chromadb.config import Settings

        self._plongeur = plongeur
        self._client = chromadb.PersistentClient(
            path=str(dossier), settings=Settings(anonymized_telemetry=False)
        )

    def _collection(self) -> Any:
        return self._client.get_or_create_collection(
            COLLECTION,
            embedding_function=None,
            metadata={"hnsw:space": "cosine", "plongeur": self._plongeur.nom},
        )

    def ids(self) -> set[str]:
        return set(self._collection().get(include=[])["ids"])

    def indexer(self, recettes: Iterable[RecetteCorpus]) -> int:
        liste = list(recettes)
        if COLLECTION in [c.name for c in self._client.list_collections()]:
            self._client.delete_collection(COLLECTION)
        if not liste:
            return 0
        self._collection().add(
            ids=[r.id for r in liste],
            documents=[r.texte_index() for r in liste],
            embeddings=self._plongeur.plonger([r.texte_index() for r in liste]),
            metadatas=[_metadonnees(r) for r in liste],
        )
        return len(liste)

    def chercher(
        self, texte: str, voies: Sequence[Voie], besoins: Sequence[Besoin], n: int = 5
    ) -> list[Correspondance]:
        collection = self._collection()
        if not besoins or not voies or collection.count() == 0:
            return []
        plongeur = (collection.metadata or {}).get("plongeur")
        if plongeur != self._plongeur.nom:
            raise ErreurIndex(
                f"index construit avec « {plongeur} », requête avec « {self._plongeur.nom} » : "
                "relance `agent-he corpus reindex`"
            )
        filtre_voie: dict[str, Any] = {"voie": {"$in": [str(v) for v in voies]}}
        filtre_besoin: dict[str, Any] = (
            {f"besoin_{besoins[0]}": True}
            if len(besoins) == 1
            else {"$or": [{f"besoin_{b}": True} for b in besoins]}
        )
        resultats = collection.query(
            query_embeddings=self._plongeur.plonger([texte]),
            n_results=min(n, collection.count()),
            where={"$and": [filtre_voie, filtre_besoin]},
        )
        ids = resultats["ids"][0]
        distances = resultats["distances"][0] if resultats["distances"] else [1.0] * len(ids)
        return [Correspondance(i, 1.0 - float(d)) for i, d in zip(ids, distances, strict=True)]
