"""Scraping éthique générique (spécification §13).

- refus de toute boutique dont les CGU ne sont pas marquées comme vérifiées ;
- lecture et respect de `robots.txt` (`urllib.robotparser`) ; robots.txt illisible ⇒ refus ;
- délai minimal entre deux requêtes vers un même domaine ; User-Agent identifiable ;
- cache local des pages, pour ne pas re-solliciter les sites inutilement.
"""

import hashlib
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from agent_he.products.boutiques import Boutique

USER_AGENT = "AgentHE/0.1 (comparatif personnel, usage non commercial)"
DUREE_CACHE_S = 7 * 24 * 3600


class ScrapingRefuse(RuntimeError):
    """La requête n'est pas autorisée (CGU non vérifiées, robots.txt, domaine étranger)."""


class Scraper:
    def __init__(
        self,
        dossier_cache: Path,
        client: httpx.Client | None = None,
        horloge: Callable[[], float] = time.monotonic,
        attendre: Callable[[float], None] = time.sleep,
        maintenant: Callable[[], float] = time.time,
    ) -> None:
        self._cache = dossier_cache
        self._client = client or httpx.Client(
            timeout=20, follow_redirects=False, headers={"User-Agent": USER_AGENT}
        )
        self._horloge = horloge
        self._attendre = attendre
        self._maintenant = maintenant
        self._robots: dict[str, RobotFileParser | None] = {}
        self._derniere_requete: dict[str, float] = {}
        self.requetes: list[str] = []
        """URL effectivement demandées (robots.txt compris), pour l'audit et les tests."""

    # --- Politesse ----------------------------------------------------------------------

    def _patienter(self, domaine: str, delai_s: float) -> None:
        precedente = self._derniere_requete.get(domaine)
        if precedente is not None:
            ecoule = self._horloge() - precedente
            if ecoule < delai_s:
                self._attendre(delai_s - ecoule)
        self._derniere_requete[domaine] = self._horloge()

    def _get(self, url: str, delai_s: float) -> httpx.Response:
        domaine = urlsplit(url).netloc
        self._patienter(domaine, delai_s)
        self.requetes.append(url)
        return self._client.get(url, headers={"User-Agent": USER_AGENT})

    def robots(self, boutique: Boutique) -> RobotFileParser | None:
        base = str(boutique.url).rstrip("/")
        if base not in self._robots:
            parseur: RobotFileParser | None = RobotFileParser(f"{base}/robots.txt")
            try:
                reponse = self._get(f"{base}/robots.txt", boutique.delai_s)
            except httpx.HTTPError:
                parseur = None
            else:
                assert parseur is not None
                if reponse.status_code == 200:
                    parseur.parse(reponse.text.splitlines())
                elif 400 <= reponse.status_code < 500:
                    parseur.parse([])  # pas de robots.txt : aucune restriction déclarée
                else:
                    parseur = None  # erreur serveur : on s'abstient
            self._robots[base] = parseur
        return self._robots[base]

    def autorise(self, boutique: Boutique, url: str) -> bool:
        if not boutique.cgu_verifiees:
            return False
        if urlsplit(url).netloc != urlsplit(str(boutique.url)).netloc:
            return False
        parseur = self.robots(boutique)
        return parseur is not None and parseur.can_fetch(USER_AGENT, url)

    # --- Cache --------------------------------------------------------------------------

    def _chemin_cache(self, url: str) -> Path:
        return self._cache / f"{hashlib.sha256(url.encode()).hexdigest()}.html"

    def page(self, boutique: Boutique, url: str) -> str:
        """Texte HTML de la page (cache local, sinon requête autorisée)."""
        if not boutique.cgu_verifiees:
            raise ScrapingRefuse(f"{boutique.nom} : CGU non vérifiées (data/boutiques.yaml)")
        chemin = self._chemin_cache(url)
        if chemin.exists() and self._maintenant() - chemin.stat().st_mtime < DUREE_CACHE_S:
            return chemin.read_text(encoding="utf-8")
        if not self.autorise(boutique, url):
            raise ScrapingRefuse(f"{url} : interdit par robots.txt ou hors du domaine")
        try:
            reponse = self._get(url, boutique.delai_s)
            reponse.raise_for_status()
        except httpx.HTTPError as exc:
            raise ScrapingRefuse(f"{url} : {exc}") from exc
        self._cache.mkdir(parents=True, exist_ok=True)
        chemin.write_text(reponse.text, encoding="utf-8")
        return reponse.text
