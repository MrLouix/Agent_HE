from pathlib import Path

import httpx
import pytest

from agent_he.products.boutiques import charger_boutiques
from agent_he.products.compare import (
    Comparateur,
    construire_produit,
    detecter_he,
    sans_ingestion,
    trier,
    volume_ml,
)
from agent_he.products.scraper import USER_AGENT, Scraper, ScrapingRefuse
from agent_he.products.shops.jsonld import produits_jsonld

from aides import DOSSIER_DONNEES, boutique, fixture, referentiel

REF = referentiel()
ROBOTS = "User-agent: *\nDisallow: /panier\nDisallow: /compte/\n"


class Horloge:
    def __init__(self) -> None:
        self.t = 1000.0
        self.attentes: list[float] = []

    def __call__(self) -> float:
        return self.t

    def attendre(self, duree: float) -> None:
        self.attentes.append(duree)
        self.t += duree


def scraper(
    tmp_path: Path, pages: dict[str, str] | None = None, robots: str = ROBOTS
) -> tuple[Scraper, list[httpx.Request], Horloge]:
    requetes: list[httpx.Request] = []

    def repondre(requete: httpx.Request) -> httpx.Response:
        requetes.append(requete)
        if requete.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        texte = (pages or {}).get(str(requete.url))
        return httpx.Response(200, text=texte) if texte else httpx.Response(404)

    horloge = Horloge()
    client = httpx.Client(transport=httpx.MockTransport(repondre))
    s = Scraper(tmp_path / "cache", client, horloge=horloge, attendre=horloge.attendre)
    return s, requetes, horloge


# --- Configuration ------------------------------------------------------------------------


def test_boutiques_du_depot_non_activees_sans_verification_des_cgu() -> None:
    boutiques = charger_boutiques(DOSSIER_DONNEES)
    assert {b.id for b in boutiques} >= {"aroma-zone", "comptoir-des-huiles"}
    assert not any(b.active for b in boutiques if not b.cgu_verifiees)


def test_verification_cgu_datee() -> None:
    with pytest.raises(ValueError):
        boutique(cgu_verifiees_le=None)
    with pytest.raises(ValueError):
        boutique(url_recherche="https://x.fr/recherche")


# --- Scraper éthique ----------------------------------------------------------------------


def test_robots_txt_respecte(tmp_path: Path) -> None:
    s, requetes, _ = scraper(tmp_path)
    with pytest.raises(ScrapingRefuse):
        s.page(boutique(), "https://www.aroma-zone.com/panier")
    with pytest.raises(ScrapingRefuse):
        s.page(boutique(), "https://www.aroma-zone.com/compte/commandes")
    # Seul robots.txt a été demandé : aucun chemin interdit n'a été requêté.
    assert [r.url.path for r in requetes] == ["/robots.txt"]
    assert all(r.headers["User-Agent"] == USER_AGENT for r in requetes)


def test_cgu_non_verifiees_aucune_requete(tmp_path: Path) -> None:
    s, requetes, _ = scraper(tmp_path)
    with pytest.raises(ScrapingRefuse):
        s.page(boutique(cgu_verifiees=False), "https://www.aroma-zone.com/produit/x")
    assert requetes == []


def test_hors_domaine_refuse(tmp_path: Path) -> None:
    s, _, _ = scraper(tmp_path)
    with pytest.raises(ScrapingRefuse):
        s.page(boutique(), "https://autre-site.example/produit")


def test_robots_indisponible_on_s_abstient(tmp_path: Path) -> None:
    def repondre(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(repondre))
    s = Scraper(tmp_path, client, attendre=lambda d: None)
    with pytest.raises(ScrapingRefuse):
        s.page(boutique(), "https://www.aroma-zone.com/produit/x")


def test_delai_et_cache(tmp_path: Path) -> None:
    url = "https://www.aroma-zone.com/produit/lavande-vraie"
    pages = {url: fixture("aroma-zone.html"), url + "-2": fixture("aroma-zone.html")}
    s, requetes, horloge = scraper(tmp_path, pages)
    s.page(boutique(), url)
    s.page(boutique(), url + "-2")
    # robots.txt puis deux pages : 5 s d'écart imposés entre chaque requête au domaine.
    assert horloge.attentes == [5, 5]
    avant = len(requetes)
    assert "Lavande" in s.page(boutique(), url)  # servi depuis le cache
    assert len(requetes) == avant


# --- Extraction et comparatif (fixtures de chaque boutique) ----------------------------------


@pytest.mark.parametrize(
    ("fichier", "he_id", "volume", "prix", "chemotype", "origine"),
    [
        ("aroma-zone.html", "lavande_vraie", 10, 4.90, "linalol", None),
        ("comptoir-des-huiles.html", "thym_thymol", 15, 6.50, "thymol", "Espagne"),
        ("compagnie-des-sens.html", "orange_douce", 30, 5.20, None, "Italie"),
        ("puressentiel.html", "lavande_vraie", 30, 12.90, None, None),
    ],
)
def test_parsing_par_boutique(
    fichier: str,
    he_id: str,
    volume: float,
    prix: float,
    chemotype: str | None,
    origine: str | None,
) -> None:
    bruts = produits_jsonld(fixture(fichier))
    assert len(bruts) == 1  # le produit en USD est ignoré
    rapproche = construire_produit(bruts[0], boutique(nom=fichier), REF)
    assert rapproche is not None
    assert rapproche.he_id == he_id
    p = rapproche.produit
    assert (p.volume_ml, p.prix, p.chemotype, p.origine) == (
        volume,
        pytest.approx(prix),
        chemotype,
        origine,
    )
    assert p.prix_ml == pytest.approx(prix / volume)


def test_carte_sans_mention_d_ingestion() -> None:
    (brut,) = produits_jsonld(fixture("comptoir-des-huiles.html"))
    rapproche = construire_produit(brut, boutique(nom="Comptoir"), REF)
    assert rapproche is not None
    carte = rapproche.carte()
    assert "interne" not in carte.lower()
    assert carte.startswith("Thym à thymol 1,5 cl — Thymus vulgaris — thymol — Espagne — 0,43 €/ml")


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [("10 ml", 10), ("Flacon 30ml", 30), ("1,5 cl", 15), ("0.1 L", 100), ("x", None)],
)
def test_volume(texte: str, attendu: float | None) -> None:
    assert volume_ml(texte) == attendu


def test_detection_he_et_chemotype() -> None:
    assert detecter_he("Thymus vulgaris ct thymol", REF) == ("thym_thymol", "thymol")
    assert detecter_he("Thymus vulgaris", REF) == (None, None)  # ambigu
    assert detecter_he("Lavandula angustifolia", REF) == ("lavande_vraie", None)
    assert sans_ingestion("Menthe poivrée - usage interne") == "Menthe poivrée"
    assert sans_ingestion("Citron (convient à l'ingestion) 10 ml") == "Citron 10 ml"


def test_tri_qualite_puis_prix() -> None:
    produits = [
        construire_produit(b, boutique(nom=f), REF)
        for f in ("aroma-zone.html", "puressentiel.html")
        for b in produits_jsonld(fixture(f))
    ]
    tries = trier([p for p in produits if p is not None])
    # Aroma-Zone cite nom latin + chémotype : qualité supérieure, malgré le prix.
    assert [p.produit.boutique for p in tries] == ["aroma-zone.html", "puressentiel.html"]


def test_comparateur(tmp_path: Path) -> None:
    pages = {
        "https://www.aroma-zone.com/recherche?q=Lavande+vraie": fixture("recherche.html"),
        "https://www.aroma-zone.com/produit/lavande-vraie": fixture("aroma-zone.html"),
    }
    s, requetes, _ = scraper(tmp_path, pages)
    inactive = boutique(id="autre", cgu_verifiees=False, cgu_verifiees_le=None)
    comparateur = Comparateur([boutique(), inactive], s, REF)
    produits, erreurs = comparateur.comparer("lavande_vraie")
    assert erreurs == []
    assert [p.produit.prix for p in produits] == [4.90]
    assert all("/panier" not in str(r.url) for r in requetes)
    assert [b.id for b in comparateur.boutiques] == ["aroma-zone"]


def test_comparateur_erreur_remontee(tmp_path: Path) -> None:
    s, _, _ = scraper(tmp_path, {}, robots="User-agent: *\nDisallow: /\n")
    produits, erreurs = Comparateur([boutique()], s, REF).comparer("lavande_vraie")
    assert produits == []
    assert erreurs and "robots.txt" in erreurs[0]
