"""Interface commune des LLM : sortie JSON validée par un schéma Pydantic."""

import json
from collections.abc import Callable
from typing import Any, Literal, Protocol, TypedDict, TypeVar

from pydantic import BaseModel, ValidationError


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


T = TypeVar("T", bound=BaseModel)


class ErreurLLM(RuntimeError):
    """Le LLM n'a pas produit de réponse exploitable."""


class LLM(Protocol):
    def complete(self, messages: list[Message], schema: type[T]) -> T:
        """Renvoie la réponse du LLM validée par `schema` (lève `ErreurLLM` sinon)."""
        ...


def _consigne_schema(schema: type[BaseModel]) -> str:
    return "Réponds uniquement par un objet JSON conforme à ce schéma JSON :\n" + json.dumps(
        schema.model_json_schema(), ensure_ascii=False
    )


def completer_structure(
    generer: Callable[[list[Message]], str], messages: list[Message], schema: type[T]
) -> T:
    """Appelle `generer`, valide le JSON, et fait **un** nouvel essai en cas d'échec."""
    echanges: list[Message] = [
        *messages,
        {"role": "system", "content": _consigne_schema(schema)},
    ]
    derniere_erreur = ""
    for _ in range(2):
        brut = generer(echanges)
        try:
            return schema.model_validate_json(brut)
        except ValidationError as exc:
            derniere_erreur = str(exc)
            echanges = [
                *echanges,
                {"role": "assistant", "content": brut},
                {
                    "role": "user",
                    "content": "Ta réponse n'est pas un JSON conforme au schéma. Erreurs :\n"
                    f"{derniere_erreur}\nRéponds à nouveau, uniquement en JSON conforme.",
                },
            ]
    raise ErreurLLM(f"réponse non conforme après un nouvel essai : {derniere_erreur}")


Repondeur = Callable[[list[Message], type[BaseModel]], Any]


class FakeLLM:
    """LLM simulé pour les tests : renvoie des réponses prédéfinies.

    `reponses` est soit une liste (consommée dans l'ordre), soit une fonction
    `(messages, schema) -> dict | str`.
    """

    def __init__(self, reponses: list[Any] | Repondeur) -> None:
        self._reponses = reponses
        self.appels: list[list[Message]] = []

    def _generer(self, messages: list[Message], schema: type[BaseModel]) -> str:
        self.appels.append(messages)
        if callable(self._reponses):
            reponse = self._reponses(messages, schema)
        else:
            if not self._reponses:
                raise ErreurLLM("FakeLLM : plus de réponse prévue")
            reponse = self._reponses.pop(0)
        return reponse if isinstance(reponse, str) else json.dumps(reponse, ensure_ascii=False)

    def complete(self, messages: list[Message], schema: type[T]) -> T:
        return completer_structure(lambda m: self._generer(m, schema), messages, schema)
