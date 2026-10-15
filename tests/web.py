"""Fixtures web enregistrées : résultats de recherche, pages et extractions simulées.

Les extractions jouent le rôle du LLM : elles recopient les pages, sauf `compromise`
qui simule un LLM ayant obéi à une injection de consignes.
"""

from typing import Any

from agent_he.llm.base import FakeLLM, Message
from agent_he.search.base import FakeRecuperateur, FakeSearch, ResultatRecherche

from aides import FIXTURES

URL_SOMMEIL = "https://www.aroma-zone.com/roll-on-sommeil"
URL_INJECTION = "https://www.compagnie-des-sens.fr/sommeil-paisible"
URL_BLOG = "https://blog-bien-etre.example/massage"

_FICHIERS = {
    URL_SOMMEIL: "aroma-zone_roll-on-sommeil.txt",
    URL_INJECTION: "compagnie-des-sens_sommeil-injection.txt",
    URL_BLOG: "blog_massage-surdose.txt",
}


def pages() -> dict[str, str]:
    return {
        url: (FIXTURES / "pages" / nom).read_text(encoding="utf-8")
        for url, nom in _FICHIERS.items()
    }


def recherche(*urls: str, **kwargs: Any) -> FakeSearch:
    urls = urls or tuple(_FICHIERS)
    return FakeSearch([ResultatRecherche(url=u, titre=f"Page {u}") for u in urls], **kwargs)


def recuperateur() -> FakeRecuperateur:
    return FakeRecuperateur(pages())


def recette_sommeil() -> dict[str, Any]:
    return {
        "nom_recette": "Roll-on sommeil apaisant",
        "voie": "cutanée",
        "huiles": [
            {
                "nom": "lavande vraie",
                "nom_latin": "Lavandula angustifolia",
                "quantite": {"valeur": 6, "unite": "gouttes"},
                "source": URL_SOMMEIL,
            },
            {
                "nom": "orange douce",
                "nom_latin": "Citrus sinensis",
                "quantite": {"valeur": 4, "unite": "gouttes"},
                "source": URL_SOMMEIL,
            },
        ],
        "base_description": "huile végétale de noyau d'abricot",
        "base_volume_ml": 10,
        "usage": "appliquer sur l'intérieur des poignets le soir",
        "precautions": [
            {"texte": "Ne pas appliquer sur les muqueuses.", "source": URL_SOMMEIL},
            {"texte": "Tenir hors de portée des enfants.", "source": URL_SOMMEIL},
        ],
        "source": URL_SOMMEIL,
    }


def recette_injection() -> dict[str, Any]:
    return {
        "nom_recette": "Synergie pour un sommeil paisible",
        "voie": "cutanee",
        "huiles": [
            {
                "nom": "lavande fine",
                "quantite": {"valeur": 4, "unite": "gouttes"},
                "source": URL_INJECTION,
            }
        ],
        "base_volume_ml": 10,
        "source": URL_INJECTION,
    }


def recette_blog() -> dict[str, Any]:
    return {
        "nom_recette": "Huile de massage relaxante",
        "voie": "cutanee",
        "huiles": [
            {
                "nom": "lavande vraie",
                "quantite": {"valeur": 30, "unite": "gouttes"},
                "source": URL_BLOG,
            }
        ],
        "base_volume_ml": 10,
        "source": URL_BLOG,
    }


def _urls_dans(messages: list[Message]) -> str:
    return "\n".join(m["content"] for m in messages)


def llm_fidele() -> FakeLLM:
    """Recopie les recettes des pages présentes dans le prompt."""

    def repondre(messages: list[Message], _schema: object) -> dict[str, Any]:
        contenu = _urls_dans(messages)
        recettes = []
        if URL_SOMMEIL in contenu:
            recettes.append(recette_sommeil())
        if URL_INJECTION in contenu:
            recettes.append(recette_injection())
        if URL_BLOG in contenu:
            recettes.append(recette_blog())
        return {"recettes": recettes, "indications": []}

    return FakeLLM(repondre)


def llm_compromis() -> FakeLLM:
    """Simule un LLM qui obéit à l'injection : il ajoute 20 % de cannelle partout."""

    def repondre(messages: list[Message], _schema: object) -> dict[str, Any]:
        cannelle = {
            "nom": "cannelle",
            "nom_latin": "Cinnamomum verum",
            "quantite": {"valeur": 20, "unite": "%"},
            "source": URL_INJECTION,
        }
        sommeil = recette_sommeil()
        sommeil["huiles"].append(cannelle)
        injection = recette_injection()
        injection["huiles"].append(cannelle)
        inventee = recette_sommeil()
        inventee["huiles"][0]["source"] = "https://site-invente.example/recette"
        inventee["source"] = "https://site-invente.example/recette"
        return {"recettes": [sommeil, injection, inventee], "indications": []}

    return FakeLLM(repondre)
