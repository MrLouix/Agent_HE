"""Interfaces de recherche et de récupération, et leurs versions simulées pour les tests."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit


class ErreurRecherche(RuntimeError):
    """La recherche ou la récupération a échoué."""


@dataclass(frozen=True)
class ResultatRecherche:
    url: str
    titre: str
    extrait: str = ""


@dataclass(frozen=True)
class Page:
    url: str
    titre: str
    texte: str


class Recherche(Protocol):
    def rechercher(
        self, requete: str, domaines: Sequence[str] | None = None, max_resultats: int = 5
    ) -> list[ResultatRecherche]: ...


class Recuperateur(Protocol):
    def recuperer(self, url: str) -> Page: ...


class FakeSearch:
    """Recherche simulée : renvoie les résultats donnés, filtrés par domaine."""

    def __init__(
        self,
        resultats: Sequence[ResultatRecherche] = (),
        echouer: bool = False,
    ) -> None:
        self._resultats = list(resultats)
        self._echouer = echouer
        self.requetes: list[tuple[str, tuple[str, ...] | None]] = []

    def rechercher(
        self, requete: str, domaines: Sequence[str] | None = None, max_resultats: int = 5
    ) -> list[ResultatRecherche]:
        self.requetes.append((requete, None if domaines is None else tuple(domaines)))
        if self._echouer:
            raise ErreurRecherche("FakeSearch : recherche web interdite dans ce test")
        retenus = [
            r
            for r in self._resultats
            if domaines is None or any(_dans_domaine(r.url, d) for d in domaines)
        ]
        return retenus[:max_resultats]


class FakeRecuperateur:
    def __init__(self, pages: dict[str, str] | Callable[[str], str]) -> None:
        self._pages = pages
        self.urls: list[str] = []

    def recuperer(self, url: str) -> Page:
        self.urls.append(url)
        if callable(self._pages):
            return Page(url=url, titre=url, texte=self._pages(url))
        if url not in self._pages:
            raise ErreurRecherche(f"page introuvable : {url}")
        return Page(url=url, titre=url, texte=self._pages[url])


def hote(url: str) -> str:
    """Nom d'hôte en minuscules, sans « www. »."""
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _dans_domaine(url: str, domaine: str) -> bool:
    h = hote(url)
    return h == domaine or h.endswith("." + domaine)
