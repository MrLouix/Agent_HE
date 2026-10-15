"""Rapport d'audit imprimable de la table de sécurité (règle §9)."""

from datetime import date

from agent_he.models import TrancheAge, Voie
from agent_he.referentiel.huiles import Referentiel
from agent_he.referentiel.securite import (
    EntreeSecurite,
    Statut,
    TableSecurite,
    TypeEntree,
    controler,
    empreinte,
    etat_effectif,
)


def _cellule(valeur: object) -> str:
    texte = "" if valeur is None else str(valeur)
    return texte.replace("|", "\\|").replace("\n", " ")


def _ligne(cellules: list[object]) -> str:
    return "| " + " | ".join(_cellule(c) for c in cellules) + " |"


def _valeur(e: EntreeSecurite) -> str:
    if e.autorise:
        return f"{e.valeur} {e.unite}"
    if e.type == TypeEntree.DRAPEAU:
        return f"{e.drapeau}" + (f" ({e.detail})" if e.detail else "")
    return f"{e.profil}" + (f" ({e.detail})" if e.detail else "")


def couverture(table: TableSecurite, referentiel: Referentiel) -> dict[str, list[str]]:
    """Pour chaque HE, les couples voie/population sans plafond applicable."""
    manques: dict[str, list[str]] = {}
    for huile in referentiel:
        absents = [
            f"{voie}/{population}"
            for voie in Voie
            for population in TrancheAge
            if table.plafond_effectif(huile.id, voie, population) is None
        ]
        if absents:
            manques[huile.id] = absents
    return manques


def rapport_markdown(table: TableSecurite, referentiel: Referentiel, jour: date) -> str:
    lignes = [f"# Audit de la table de sécurité — {jour.isoformat()}", ""]

    problemes = controler(table, referentiel)
    lignes += ["## Contrôles automatiques", ""]
    lignes += [f"- ❌ {p}" for p in problemes] or ["- ✅ Aucun problème bloquant."]
    lignes.append("")

    lignes += ["## Entrées", ""]
    entete = ["id", "HE", "nom latin", "type", "voie", "population", "valeur", "page"]
    lignes.append(_ligne([*entete, "statut", "citation"]))
    lignes.append(_ligne(["---"] * (len(entete) + 2)))
    for e in table:
        lignes.append(
            _ligne(
                [
                    e.id,
                    e.he_id,
                    e.nom_latin,
                    e.type,
                    e.voie,
                    e.population,
                    _valeur(e),
                    e.source.page,
                    e.statut,
                    f"« {e.source.citation} »",
                ]
            )
        )
    if not table.entrees:
        lignes.append("_Table vide : aucun dosage n'est possible._")
    lignes.append("")

    lignes += ["## Couverture", ""]
    lignes.append(
        "HE et couples voie/population **sans plafond validé** (donc sans dosage possible) :"
    )
    lignes.append("")
    for he_id, absents in couverture(table, referentiel).items():
        total = len(Voie) * len(TrancheAge)
        if len(absents) == total:
            lignes.append(f"- **{he_id}** : aucune voie ni population couverte")
        else:
            lignes.append(f"- **{he_id}** : {', '.join(absents)}")
    lignes.append("")

    lignes += ["## À traiter", ""]
    a_traiter: list[str] = []
    for e in table:
        etat = etat_effectif(e)
        if e.statut in (Statut.BROUILLON, Statut.VERIFIE):
            a_traiter.append(f"- {e.id} : statut {e.statut}")
        if e.statut == Statut.VALIDE and not etat.valide:
            a_traiter.append(f"- {e.id} : empreinte invalide (attendue {empreinte(e)[:12]}…)")
        if e.saisie.methode == "assistee" and e.verification.resultat is None:
            a_traiter.append(f"- {e.id} : saisie assistée non vérifiée")
    lignes += a_traiter or ["_Rien à traiter._"]
    lignes.append("")

    lignes += ["## Interprétations", ""]
    interpretations = [f"- {e.id} : {e.interpretation}" for e in table if e.interpretation]
    lignes += interpretations or ["_Aucune interprétation._"]
    lignes.append("")
    return "\n".join(lignes)
