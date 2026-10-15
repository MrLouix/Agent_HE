"""Connecteur Tavily : recherche filtrée par liste blanche (`include_domains`)."""

from collections.abc import Sequence
from typing import Any

import httpx

from agent_he.search.base import ErreurRecherche, ResultatRecherche

URL_TAVILY = "https://api.tavily.com/search"


class TavilySearch:
    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=30)

    def rechercher(
        self, requete: str, domaines: Sequence[str] | None = None, max_resultats: int = 5
    ) -> list[ResultatRecherche]:
        corps: dict[str, Any] = {
            "query": requete,
            "max_results": max_resultats,
            "search_depth": "basic",
        }
        if domaines:
            corps["include_domains"] = list(domaines)
        try:
            reponse = self._client.post(
                URL_TAVILY, json=corps, headers={"Authorization": f"Bearer {self._api_key}"}
            )
            reponse.raise_for_status()
            resultats = reponse.json().get("results", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise ErreurRecherche(f"recherche Tavily en échec : {exc}") from exc
        return [
            ResultatRecherche(
                url=str(r["url"]), titre=str(r.get("title", "")), extrait=str(r.get("content", ""))
            )
            for r in resultats
            if isinstance(r, dict) and r.get("url")
        ]
