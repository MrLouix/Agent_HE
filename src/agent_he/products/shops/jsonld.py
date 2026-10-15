"""Extraction des produits depuis les données structurées schema.org (JSON-LD).

Les boutiques publient en général un bloc `<script type="application/ld+json">` de type
`Product` : on s'appuie sur ce format standard plutôt que sur la mise en page HTML.
"""

import json
import re
from collections.abc import Iterator
from typing import Any

_BLOC = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _objets(donnees: Any) -> Iterator[dict[str, Any]]:
    if isinstance(donnees, list):
        for d in donnees:
            yield from _objets(d)
    elif isinstance(donnees, dict):
        yield donnees
        if "@graph" in donnees:
            yield from _objets(donnees["@graph"])


def _est_produit(objet: dict[str, Any]) -> bool:
    type_ = objet.get("@type")
    types = type_ if isinstance(type_, list) else [type_]
    return "Product" in types


def _offre(objet: dict[str, Any]) -> dict[str, Any] | None:
    offres = objet.get("offers")
    if isinstance(offres, list):
        offres = offres[0] if offres else None
    if isinstance(offres, dict) and offres.get("@type") == "AggregateOffer":
        return {"price": offres.get("lowPrice"), "priceCurrency": offres.get("priceCurrency")}
    return offres if isinstance(offres, dict) else None


def produits_jsonld(html: str) -> list[dict[str, Any]]:
    """Produits bruts : nom, description, prix (EUR), url, propriétés additionnelles."""
    produits: list[dict[str, Any]] = []
    for bloc in _BLOC.findall(html):
        try:
            donnees = json.loads(bloc)
        except json.JSONDecodeError:
            continue
        for objet in _objets(donnees):
            if not _est_produit(objet):
                continue
            offre = _offre(objet)
            if offre is None or offre.get("priceCurrency", "EUR") != "EUR":
                continue
            try:
                prix = float(str(offre.get("price")).replace(",", "."))
            except ValueError:
                continue
            proprietes = {
                str(p.get("name", "")).lower(): str(p.get("value", ""))
                for p in objet.get("additionalProperty", [])
                if isinstance(p, dict)
            }
            origine = objet.get("countryOfOrigin")
            if isinstance(origine, dict):
                origine = origine.get("name")
            produits.append(
                {
                    "nom": str(objet.get("name", "")).strip(),
                    "description": str(objet.get("description", "")),
                    "prix": prix,
                    "url": offre.get("url") or objet.get("url"),
                    "origine": origine,
                    "proprietes": proprietes,
                }
            )
    return produits
