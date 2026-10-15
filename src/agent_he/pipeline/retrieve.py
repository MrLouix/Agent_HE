"""Récupération des pages web : liste blanche, puis passage ouvert optionnel."""

from collections.abc import Sequence

from agent_he.search.base import ErreurRecherche, Page, Recherche, Recuperateur
from agent_he.search.fetch import contient_injection


def recuperer_pages(
    recherche: Recherche,
    recuperateur: Recuperateur,
    requetes: Sequence[str],
    liste_blanche: Sequence[str],
    *,
    ouverte: bool,
    max_resultats: int,
    notes: list[str],
) -> list[Page]:
    resultats = []
    for requete in requetes:
        resultats += recherche.rechercher(requete, liste_blanche, max_resultats)
        if ouverte:
            resultats += recherche.rechercher(requete, None, max_resultats)
    pages: list[Page] = []
    vues: set[str] = set()
    for resultat in resultats:
        if resultat.url in vues:
            continue
        vues.add(resultat.url)
        try:
            page = recuperateur.recuperer(resultat.url)
        except ErreurRecherche as exc:
            notes.append(str(exc))
            continue
        if contient_injection(page.texte):
            notes.append(f"Page écartée (consignes adressées à une IA) : {page.url}")
            continue
        if page.texte.strip():
            pages.append(page)
    return pages
