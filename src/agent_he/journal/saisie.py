"""Aides à la saisie : mélange libre normalisé, rappels des utilisations sans retour."""

import re
from datetime import UTC, datetime, timedelta

from agent_he.journal.repository import ErreurJournal, Journal
from agent_he.models import DoseHE, Quantite
from agent_he.pipeline.normalize import normaliser_unite
from agent_he.referentiel.huiles import Referentiel
from agent_he.storage.favorites import Historique


def parser_melange(texte: str, referentiel: Referentiel) -> list[DoseHE]:
    """« lavande fine:3:gouttes; orange douce:2:gouttes » ⇒ doses normalisées.

    Le journal n'est pas une source : `sources` reste vide.
    """
    doses: list[DoseHE] = []
    for morceau in filter(None, (m.strip() for m in re.split(r"[;\n]+", texte))):
        parties = [p.strip() for p in morceau.split(":")]
        if len(parties) != 3:
            raise ErreurJournal(f"format attendu « nom:quantité:unité » : {morceau}")
        nom, valeur, unite_brute = parties
        he_id = referentiel.normaliser(nom)
        if he_id is None:
            raise ErreurJournal(f"HE inconnue ou ambiguë : {nom}")
        unite = normaliser_unite(unite_brute)
        try:
            quantite = Quantite(valeur=float(valeur.replace(",", ".")), unite=unite)  # type: ignore[arg-type]
        except ValueError as exc:
            raise ErreurJournal(f"quantité invalide : {morceau}") from exc
        huile = referentiel[he_id]
        doses.append(
            DoseHE(he_id=he_id, nom=huile.nom, nom_latin=huile.nom_latin, quantite=quantite)
        )
    if not doses:
        raise ErreurJournal("mélange vide")
    return doses


def utilisations_sans_retour(historique: Historique, journal: Journal, jours: int = 3) -> list[str]:
    """Recettes consultées récemment et sans entrée de journal depuis."""
    limite = datetime.now(UTC) - timedelta(days=jours)
    vues: dict[str, datetime] = {}
    for e in historique.lister():
        if e.recette_ref and e.fiche.recette is not None and e.horodatage >= limite:
            vues.setdefault(e.recette_ref, e.horodatage)
    rappels: list[str] = []
    for ref, quand in vues.items():
        if not any(u.horodatage >= quand for u, _ in journal.lister(recette_ref=ref)):
            rappels.append(ref)
    return rappels
