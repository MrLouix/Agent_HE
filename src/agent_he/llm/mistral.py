"""Connecteur Mistral (API chat completions, sortie JSON)."""

from typing import Any

import httpx

from agent_he.llm.base import ErreurLLM, Message, T, completer_structure

URL_MISTRAL = "https://api.mistral.ai/v1/chat/completions"


class MistralLLM:
    def __init__(
        self,
        api_key: str,
        modele: str = "mistral-large-latest",
        client: httpx.Client | None = None,
        temperature: float = 0.0,
    ) -> None:
        self._api_key = api_key
        self._modele = modele
        self._client = client or httpx.Client(timeout=60)
        self._temperature = temperature

    def _generer(self, messages: list[Message]) -> str:
        corps: dict[str, Any] = {
            "model": self._modele,
            "messages": messages,
            "temperature": self._temperature,
            "response_format": {"type": "json_object"},
        }
        try:
            reponse = self._client.post(
                URL_MISTRAL,
                json=corps,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            reponse.raise_for_status()
            contenu = reponse.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise ErreurLLM(f"appel Mistral en échec : {exc}") from exc
        if not isinstance(contenu, str):
            raise ErreurLLM("réponse Mistral inattendue")
        return contenu

    def complete(self, messages: list[Message], schema: type[T]) -> T:
        return completer_structure(self._generer, messages, schema)
