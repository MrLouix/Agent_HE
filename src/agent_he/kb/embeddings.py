"""Plongements de texte : local (hachage, hors ligne) ou Mistral."""

import hashlib
import math
from collections.abc import Sequence
from typing import Protocol

import httpx

from agent_he.referentiel.huiles import simplifier

URL_MISTRAL_EMBED = "https://api.mistral.ai/v1/embeddings"


class Plongeur(Protocol):
    nom: str

    def plonger(self, textes: Sequence[str]) -> list[list[float]]: ...


def _racine(mot: str) -> str:
    """Racinisation minimale : pluriels et terminaisons verbales courantes."""
    for suffixe in ("ements", "ement", "ations", "ation", "ir", "er", "es", "s", "e"):
        if len(mot) > len(suffixe) + 3 and mot.endswith(suffixe):
            return mot[: -len(suffixe)]
    return mot


def _normer(vecteur: list[float]) -> list[float]:
    norme = math.sqrt(sum(v * v for v in vecteur))
    return [v / norme for v in vecteur] if norme else vecteur


class PlongeurLocal:
    """Sac de mots haché : déterministe, hors ligne, sans dépendance."""

    nom = "local-hachage-v1"

    def __init__(self, dimension: int = 512) -> None:
        self.dimension = dimension

    def _vecteur(self, texte: str) -> list[float]:
        vecteur = [0.0] * self.dimension
        for mot in simplifier(texte).split():
            if len(mot) < 3:
                continue
            empreinte = hashlib.blake2b(_racine(mot).encode(), digest_size=8).digest()
            vecteur[int.from_bytes(empreinte, "big") % self.dimension] += 1.0
        return _normer(vecteur)

    def plonger(self, textes: Sequence[str]) -> list[list[float]]:
        return [self._vecteur(t) for t in textes]


class PlongeurMistral:
    nom = "mistral-embed"

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=60)

    def plonger(self, textes: Sequence[str]) -> list[list[float]]:
        if not textes:
            return []
        reponse = self._client.post(
            URL_MISTRAL_EMBED,
            json={"model": "mistral-embed", "input": list(textes)},
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        reponse.raise_for_status()
        return [_normer([float(v) for v in d["embedding"]]) for d in reponse.json()["data"]]


def cosinus(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))
