"""Comparatif : volume ⇒ prix/ml, rapprochement avec le référentiel, tri qualité puis prix/ml."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from agent_he.models import Produit
from agent_he.products.boutiques import Boutique
from agent_he.products.scraper import Scraper, ScrapingRefuse
from agent_he.products.shops.jsonld import produits_jsonld
from agent_he.referentiel.huiles import Huile, Referentiel, simplifier

_VOLUME = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ml|millilitres?|cl|l)\b", re.IGNORECASE)
_LABELS = {"bio": "Bio", "ab": "Bio", "hebbd": "HEBBD", "hect": "HECT", "ecocert": "Ecocert"}
# Aucune mention d'ingestion sur les cartes produits (spécification §13).
_TERMES_INGESTION = r"(?:usage interne|voie orale|ingestion|ingérer|alimentaire|comestible)"
_PARENTHESE_INGESTION = re.compile(rf"\s*\([^)]*{_TERMES_INGESTION}[^)]*\)", re.IGNORECASE)
_SEGMENT_INGESTION = re.compile(rf"\s*[-–,]?\s*{_TERMES_INGESTION}(?:\s+possible)?", re.IGNORECASE)


def volume_ml(texte: str) -> float | None:
    """« Flacon 10 ml », « 1,5 cl », « 0.1 L » ⇒ volume en ml."""
    m = _VOLUME.search(texte)
    if m is None:
        return None
    valeur = float(m.group(1).replace(",", "."))
    unite = m.group(2).lower()
    facteur = {"cl": 10.0, "l": 1000.0}.get(unite, 1.0)
    return valeur * facteur


def sans_ingestion(texte: str) -> str:
    sans_parentheses = _PARENTHESE_INGESTION.sub("", texte)
    return re.sub(r"\s+", " ", _SEGMENT_INGESTION.sub("", sans_parentheses)).strip()


def detecter_he(texte: str, referentiel: Referentiel) -> tuple[str | None, str | None]:
    """(he_id, chémotype) d'après le nom latin et le chémotype cités dans le texte."""
    t = f" {simplifier(texte)} "
    candidates: list[Huile] = [
        h for h in referentiel if any(f" {simplifier(n)} " in t for n in h.noms_latins())
    ]
    if not candidates:
        candidates = [h for h in referentiel if any(f" {simplifier(n)} " in t for n in h.noms_fr)]
    for huile in candidates:
        for chemotype in huile.chemotypes:
            cite = f" {simplifier(chemotype)} " in t
            if cite and len([h for h in candidates if chemotype in h.chemotypes]) == 1:
                return huile.id, chemotype
    if len(candidates) == 1:
        return candidates[0].id, None
    return None, None


def labels(texte: str) -> list[str]:
    mots = set(simplifier(texte).split())
    return sorted({libelle for cle, libelle in _LABELS.items() if cle in mots})


@dataclass(frozen=True)
class ProduitRapproche:
    produit: Produit
    he_id: str

    @property
    def qualite(self) -> int:
        """Nom latin + chémotype + origine renseignés (0 à 3)."""
        p = self.produit
        return sum(bool(x) for x in (p.nom_latin, p.chemotype, p.origine))

    def carte(self) -> str:
        p = self.produit
        return " — ".join(
            [
                p.nom,
                p.nom_latin or "nom latin non indiqué",
                p.chemotype or "chémotype non indiqué",
                p.origine or "origine non indiquée",
                f"{p.prix_ml:.2f} €/ml".replace(".", ","),
                str(p.url),
            ]
        )


def construire_produit(
    brut: dict[str, Any], boutique: Boutique, referentiel: Referentiel
) -> ProduitRapproche | None:
    texte = " ".join(
        [brut["nom"], brut["description"], *brut["proprietes"].keys(), *brut["proprietes"].values()]
    )
    volume = (
        volume_ml(brut["nom"])
        or volume_ml(brut["proprietes"].get("contenance", ""))
        or (volume_ml(brut["description"]))
    )
    he_id, chemotype = detecter_he(texte, referentiel)
    if volume is None or he_id is None or not brut.get("url") or brut["prix"] <= 0:
        return None
    huile = referentiel[he_id]
    latin_cite = any(simplifier(n) in simplifier(texte) for n in huile.noms_latins())
    produit = Produit(
        boutique=boutique.nom,
        nom=sans_ingestion(brut["nom"]) or huile.nom,
        nom_latin=huile.nom_latin if latin_cite else None,
        chemotype=chemotype,
        origine=brut.get("origine") or brut["proprietes"].get("origine") or None,
        labels=labels(texte),
        volume_ml=volume,
        prix=brut["prix"],
        url=brut["url"],
    )
    return ProduitRapproche(produit, he_id)


def trier(produits: Sequence[ProduitRapproche]) -> list[ProduitRapproche]:
    """Qualité d'abord, puis prix au ml croissant."""
    return sorted(produits, key=lambda p: (-p.qualite, p.produit.prix_ml))


class Comparateur:
    def __init__(
        self, boutiques: Sequence[Boutique], scraper: Scraper, referentiel: Referentiel
    ) -> None:
        self.boutiques = [b for b in boutiques if b.active]
        self._scraper = scraper
        self._referentiel = referentiel

    def produits_page(self, boutique: Boutique, url: str) -> list[ProduitRapproche]:
        html = self._scraper.page(boutique, url)
        return [
            p
            for brut in produits_jsonld(html)
            if (
                p := construire_produit(
                    {**brut, "url": brut["url"] or url}, boutique, self._referentiel
                )
            )
        ]

    def comparer(self, he_id: str, max_pages: int = 3) -> tuple[list[ProduitRapproche], list[str]]:
        """Produits de l'HE dans les boutiques actives, triés ; avec les erreurs rencontrées."""
        huile = self._referentiel[he_id]
        produits: list[ProduitRapproche] = []
        erreurs: list[str] = []
        for boutique in self.boutiques:
            assert boutique.url_recherche and boutique.motif_lien_produit
            recherche = boutique.url_recherche.replace("{q}", huile.nom.replace(" ", "+"))
            try:
                html = self._scraper.page(boutique, recherche)
                liens = list(dict.fromkeys(re.findall(boutique.motif_lien_produit, html)))
                for lien in liens[:max_pages]:
                    url = (
                        lien
                        if lien.startswith("http")
                        else f"{str(boutique.url).rstrip('/')}{lien}"
                    )
                    produits += [p for p in self.produits_page(boutique, url) if p.he_id == he_id]
            except ScrapingRefuse as exc:
                erreurs.append(str(exc))
        return trier(produits), erreurs
