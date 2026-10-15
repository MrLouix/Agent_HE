"""Récupération d'une page et extraction de son texte principal."""

import re

import httpx
import trafilatura

from agent_he.search.base import ErreurRecherche, Page

USER_AGENT = "AgentHE/0.1 (outil personnel de recherche en aromatherapie)"

# Consignes adressées à une IA dans une page : la page est écartée (fail closed).
_INJECTION = re.compile(
    r"(ignore[rz]?\s+(toutes\s+)?(les\s+|tes\s+|vos\s+)?(r[eè]gles|instructions|consignes)"
    r"|ignore\s+(all\s+|any\s+)?(previous\s+|prior\s+)?(instructions|rules)"
    r"|disregard\s+(all\s+|the\s+)?(previous\s+)?instructions"
    r"|system\s+prompt|prompt\s+syst[eè]me"
    r"|you\s+are\s+now|tu\s+es\s+d[ée]sormais)",
    re.IGNORECASE,
)


def contient_injection(texte: str) -> bool:
    """Vrai si le texte contient des consignes adressées à un LLM."""
    return bool(_INJECTION.search(texte))


def texte_principal(html: str) -> str:
    texte = trafilatura.extract(html, include_comments=False, include_tables=True)
    return texte or ""


class RecuperateurHttp:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        )

    def recuperer(self, url: str) -> Page:
        try:
            reponse = self._client.get(url)
            reponse.raise_for_status()
        except httpx.HTTPError as exc:
            raise ErreurRecherche(f"récupération de {url} en échec : {exc}") from exc
        html = reponse.text
        titre = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        return Page(
            url=url,
            titre=titre.group(1).strip() if titre else url,
            texte=texte_principal(html),
        )
