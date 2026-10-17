"""Administration des fichiers de configuration `boutiques.yaml` et `securite.yaml`.

Logique sans Streamlit, utilisée par les pages d'administration :
- toute écriture est précédée d'une validation complète du fichier (pydantic) ;
- les commentaires de tête des fichiers sont conservés ;
- côté sécurité, le cycle de vie de la règle (§6, §7) est respecté : identifiants
  séquentiels jamais réutilisés, aucune suppression (P6), et toute modification d'un champ
  de fond d'une entrée vérifiée ou validée la ramène en brouillon.
"""

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import TypeAdapter

from agent_he.products.boutiques import Boutique
from agent_he.referentiel.securite import (
    EntreeSecurite,
    ErreurCycle,
    Statut,
    Validation,
    ecrire_entrees,
    empreinte,
    entete_fichier,
    lire_entrees,
)

FICHIER_BOUTIQUES = "boutiques.yaml"
FICHIER_SECURITE = "securite.yaml"

# Champs de boutiques.yaml modifiables depuis l'interface ; les autres sont en lecture seule.
CHAMPS_BOUTIQUE_MODIFIABLES = (
    "url_cgu",
    "cgu_verifiees",
    "cgu_verifiees_le",
    "delai_s",
    "url_recherche",
    "motif_lien_produit",
)


_LISTE_BOUTIQUES = TypeAdapter(list[Boutique])


class ErreurAdmin(ValueError):
    """Modification refusée (fichier invalide, entrée introuvable, transition interdite)."""


def _entete(chemin: Path) -> str:
    return entete_fichier(chemin) if chemin.exists() else ""


# --- Boutiques -----------------------------------------------------------------------


def lire_boutiques(dossier: Path) -> list[Boutique]:
    chemin = dossier / FICHIER_BOUTIQUES
    return _LISTE_BOUTIQUES.validate_python(yaml.safe_load(chemin.read_text("utf-8")) or [])


def modifier_boutique(dossier: Path, boutique_id: str, changements: dict[str, Any]) -> Boutique:
    """Met à jour les champs modifiables d'une boutique et réécrit le fichier.

    Les données brutes sont modifiées sur place (les champs non touchés restent écrits à
    l'identique), puis l'ensemble est validé avant écriture.
    """
    interdits = set(changements) - set(CHAMPS_BOUTIQUE_MODIFIABLES)
    if interdits:
        raise ErreurAdmin(f"champs en lecture seule : {sorted(interdits)}")
    chemin = dossier / FICHIER_BOUTIQUES
    brut: list[dict[str, Any]] = yaml.safe_load(chemin.read_text("utf-8")) or []
    cible = next((b for b in brut if b.get("id") == boutique_id), None)
    if cible is None:
        raise ErreurAdmin(f"boutique introuvable : {boutique_id}")
    for champ, valeur in changements.items():
        if isinstance(valeur, str):
            valeur = valeur.strip() or None
        cible[champ] = valeur
    if not cible.get("cgu_verifiees"):
        cible["cgu_verifiees_le"] = None
    try:
        boutiques = _LISTE_BOUTIQUES.validate_python(brut)
    except ValueError as exc:
        raise ErreurAdmin(str(exc)) from exc
    corps = yaml.safe_dump(brut, allow_unicode=True, sort_keys=False, width=100)
    chemin.write_text(_entete(chemin) + corps, encoding="utf-8")
    return next(b for b in boutiques if b.id == boutique_id)


# --- Table de sécurité ---------------------------------------------------------------


def lire_securite(dossier: Path) -> list[EntreeSecurite]:
    return lire_entrees(dossier / FICHIER_SECURITE)


def prochain_id(entrees: list[EntreeSecurite]) -> str:
    """Identifiant suivant le plus grand existant (jamais réutilisé, entrées retirées comprises)."""
    numeros = [int(e.id.removeprefix("SEC-")) for e in entrees]
    return f"SEC-{max(numeros, default=0) + 1:04d}"


def _ecrire_securite(dossier: Path, entrees: list[EntreeSecurite]) -> None:
    chemin = dossier / FICHIER_SECURITE
    ecrire_entrees(chemin, entrees, entete=_entete(chemin))


def enregistrer_entree(dossier: Path, donnees: dict[str, Any]) -> EntreeSecurite:
    """Crée (sans `id`) ou met à jour une entrée à partir des champs saisis.

    Les champs de suivi (vérification, validation, statut, retrait) ne sont jamais pris dans
    `donnees` : ils évoluent uniquement par `verifier`, `valider` et `retirer`.
    """
    entrees = lire_securite(dossier)
    suivi = {"verification", "validation", "statut", "motif_retrait"}
    saisie = {k: v for k, v in donnees.items() if k not in suivi}
    entree_id = saisie.get("id")
    index = next((i for i, e in enumerate(entrees) if e.id == entree_id), None)
    if entree_id is None:
        saisie["id"] = prochain_id(entrees)
    elif index is None:
        raise ErreurAdmin(f"entrée introuvable : {entree_id}")
    else:
        ancienne = entrees[index]
        if ancienne.statut == Statut.RETIRE:
            raise ErreurAdmin(f"{entree_id} : entrée retirée, non modifiable")
        for champ in suivi:
            saisie[champ] = getattr(ancienne, champ)
    try:
        entree = EntreeSecurite.model_validate(saisie)
    except ValueError as exc:
        raise ErreurAdmin(str(exc)) from exc
    if index is None:
        entrees.append(entree)
    else:
        # Règle §6 : modifier un champ de fond annule vérification et validation.
        if entree.statut in (Statut.VERIFIE, Statut.VALIDE) and empreinte(entree) != empreinte(
            entrees[index]
        ):
            entree = entree.model_copy(
                update={"statut": Statut.BROUILLON, "validation": Validation()}
            )
        entrees[index] = entree
    _ecrire_securite(dossier, entrees)
    return entree


def remplacer_entree(dossier: Path, entree: EntreeSecurite) -> None:
    """Réécrit une entrée existante après une opération du cycle de vie."""
    entrees = lire_securite(dossier)
    index = next((i for i, e in enumerate(entrees) if e.id == entree.id), None)
    if index is None:
        raise ErreurAdmin(f"entrée introuvable : {entree.id}")
    entrees[index] = entree
    _ecrire_securite(dossier, entrees)


def retirer(entree: EntreeSecurite, motif: str, le: date | None = None) -> EntreeSecurite:
    """Retire une entrée (P6 : jamais supprimée) ; le motif est obligatoire."""
    if entree.statut == Statut.RETIRE:
        raise ErreurCycle(f"{entree.id} : entrée déjà retirée")
    if not motif.strip():
        raise ErreurCycle(f"{entree.id} : un retrait exige un motif")
    jour = f" ({le.isoformat()})" if le else ""
    return entree.model_copy(
        update={"statut": Statut.RETIRE, "motif_retrait": f"{motif.strip()}{jour}"}
    )
