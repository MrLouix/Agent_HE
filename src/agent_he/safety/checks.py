"""Contrôles communs aux deux priorités (spécification §4, §6) et validateur final.

`controler_recette` ne corrige jamais une dose : une recette hors plafond est rejetée.
`assert_fiche_sure` est le dernier rempart, appelé sur toute fiche avant affichage.
"""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from agent_he.models import (
    AVERTISSEMENT_SYNTHESE,
    MODES_AVEC_RECETTE,
    Drapeau,
    Fiche,
    Modele,
    Precaution,
    Questionnaire,
    Recette,
    TexteNonVide,
    Voie,
)
from agent_he.referentiel.huiles import Referentiel
from agent_he.referentiel.securite import TableSecurite
from agent_he.safety.doses import avec_concentrations, total_pct
from agent_he.safety.questionnaire import he_exclues, profil_exclu, profils_actifs

PREFIXE_SOURCE_TABLE = "securite:"

TEXTES_DRAPEAUX: dict[Drapeau, str] = {
    Drapeau.PHOTOTOXIQUE: (
        "Photosensibilisante : ne pas s'exposer au soleil ni aux UV après application cutanée."
    ),
    Drapeau.DERMOCAUSTIQUE: (
        "Dermocaustique : irritante pour la peau et les muqueuses, toujours très diluée."
    ),
    Drapeau.NEUROTOXIQUE: "Neurotoxique à forte dose (cétones) : respecter strictement le dosage.",
    Drapeau.HORMONE_LIKE: "Effet hormone-like : à éviter en cas de pathologie hormonodépendante.",
    Drapeau.ALLERGENE: "Contient des composés allergisants : test cutané recommandé.",
    Drapeau.INTERACTION_MEDICAMENT: "Risque d'interaction médicamenteuse",
}


class IndicationSource(Modele):
    """Indication de sécurité relevée dans une source (pour la règle de contradiction)."""

    he_id: TexteNonVide
    type: Literal["plafond", "contre_indication"]
    voie: Voie | None = None
    valeur: float | None = None
    profil: str | None = None
    source: TexteNonVide


@dataclass
class Verdict:
    conforme: bool
    recette: Recette | None
    rejets: list[str] = field(default_factory=list)
    controles: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)


class FicheNonSure(AssertionError):
    """Une fiche viole un invariant de sécurité ; elle ne doit jamais être affichée."""


def _precautions_table(
    recette: Recette, q: Questionnaire, table: TableSecurite
) -> tuple[list[Precaution], list[str]]:
    precautions: list[Precaution] = []
    avertissements: list[str] = []
    for dose in recette.huiles:
        for r in table.restrictions(dose.he_id):
            if r.drapeau is None:
                continue
            texte = f"{dose.nom} — {TEXTES_DRAPEAUX[r.drapeau]}"
            if r.detail:
                texte += f" ({r.detail})"
            if not r.valide:
                texte += " [entrée de sécurité non validée]"
            precautions.append(
                Precaution(texte=texte, sources=[f"{PREFIXE_SOURCE_TABLE}{r.entree_id}"])
            )
            if r.drapeau == Drapeau.ALLERGENE and q.allergies:
                avertissements.append(
                    f"{dose.nom} est allergisante : test cutané indispensable "
                    "(allergies déclarées)."
                )
    return precautions, avertissements


def _union_precautions(*listes: Iterable[Precaution]) -> list[Precaution]:
    vues: dict[str, Precaution] = {}
    for liste in listes:
        for p in liste:
            if p.texte in vues:
                sources = sorted({*vues[p.texte].sources, *p.sources})
                vues[p.texte] = p.model_copy(update={"sources": sources})
            else:
                vues[p.texte] = p
    return list(vues.values())


def controler_recette(
    recette: Recette,
    questionnaire: Questionnaire,
    table: TableSecurite,
    referentiel: Referentiel,
    *,
    convention_gouttes_ml: int,
    exclusions_perso: Mapping[str, str] | Collection[str] = (),
    indications: Iterable[IndicationSource] = (),
) -> Verdict:
    """Applique les contrôles communs ; une recette non conforme est rejetée, jamais corrigée."""
    rejets: list[str] = []
    controles: list[str] = []
    contradictions: list[str] = []
    population = questionnaire.age

    motif = profil_exclu(questionnaire)
    if motif is not None:
        return Verdict(False, None, rejets=[motif.texte], controles=["profil_exclu"])

    recette = avec_concentrations(recette, convention_gouttes_ml)
    interdites = he_exclues(questionnaire, table)
    perso = (
        dict(exclusions_perso)
        if isinstance(exclusions_perso, Mapping)
        else dict.fromkeys(exclusions_perso, "exclusion personnelle")
    )
    actifs = {str(p) for p in profils_actifs(questionnaire)}
    indications = list(indications)

    for dose in recette.huiles:
        he = dose.he_id
        if he not in referentiel:
            rejets.append(f"{dose.nom} : HE inconnue du référentiel")
            controles.append("he_inconnue")
            continue
        if he in perso:
            rejets.append(f"{dose.nom} : dans ta liste d'exclusion personnelle ({perso[he]})")
            controles.append("exclusion_personnelle")
        if he in interdites:
            rejets.append(f"{dose.nom} : {interdites[he]}")
            controles.append("interdit_profil")

        # Règle de contradiction (§4) : contre-indications relevées dans les sources.
        for ind in indications:
            if ind.he_id == he and ind.type == "contre_indication" and ind.profil in actifs:
                rejets.append(f"{dose.nom} : contre-indiquée pour ce profil selon {ind.source}")
                contradictions.append(
                    f"{dose.nom} : {ind.source} la contre-indique pour « {ind.profil} » ; "
                    "l'indication la plus restrictive est retenue."
                )
                controles.append("contradiction")

        # Croisement (§4) : la table de sécurité est la seconde référence obligatoire.
        if not table.couverte(he):
            rejets.append(f"{dose.nom} : absente de la table de sécurité (aucune entrée validée)")
            controles.append("fail_closed")
            continue
        # Fail closed : sans plafond validé pour la voie et la population, aucun dosage.
        plafond = table.plafond_effectif(he, recette.voie, population, dose.chemotype)
        if plafond is None:
            rejets.append(
                f"{dose.nom} : aucun plafond validé dans la table de sécurité pour "
                f"la voie {recette.voie} et la population {population}"
            )
            controles.append("fail_closed")
            continue
        for ind in indications:
            if (
                ind.he_id == he
                and ind.type == "plafond"
                and ind.valeur is not None
                and ind.voie in (None, recette.voie)
                and ind.valeur != plafond
            ):
                contradictions.append(
                    f"{dose.nom} : {ind.source} indique {ind.valeur:g} % au maximum, la table "
                    f"de sécurité {plafond:g} % ; la valeur la plus restrictive est retenue."
                )
                controles.append("contradiction")
                plafond = min(plafond, ind.valeur)
        if dose.concentration_pct is None:
            rejets.append(f"{dose.nom} : concentration non calculable (volume de la base inconnu)")
            controles.append("concentration_inconnue")
        elif dose.concentration_pct > plafond:
            rejets.append(
                f"{dose.nom} : {dose.concentration_pct:g} % dépasse le plafond de {plafond:g} %"
            )
            controles.append("plafond_he")

    plafond_total = table.plafond_total(recette.voie, population)
    total = total_pct(recette, convention_gouttes_ml)
    if plafond_total is None:
        rejets.append(f"Aucun plafond total validé pour la voie {recette.voie} ({population})")
        controles.append("fail_closed_total")
    elif total is not None and total > plafond_total:
        rejets.append(f"Total du mélange {total:g} % > plafond total de {plafond_total:g} %")
        controles.append("plafond_total")

    if rejets:
        return Verdict(
            False, None, rejets=rejets, controles=controles, contradictions=contradictions
        )

    precautions_table, avertissements = _precautions_table(recette, questionnaire, table)
    recette = recette.model_copy(
        update={"precautions": _union_precautions(recette.precautions, precautions_table)}
    )
    if precautions_table:
        controles.append("drapeaux")
    return Verdict(
        True,
        recette,
        controles=controles,
        contradictions=contradictions,
        avertissements=avertissements,
    )


def assert_fiche_sure(
    fiche: Fiche,
    questionnaire: Questionnaire,
    table: TableSecurite,
    referentiel: Referentiel,
    *,
    voies_demandees: Collection[Voie] | None = None,
    exclusions_perso: Collection[str] = (),
    sources_recuperees: Collection[str] | None = None,
) -> None:
    """Lève `FicheNonSure` si la fiche viole un invariant de sécurité (spec §14)."""
    if fiche.mode not in MODES_AVEC_RECETTE:
        if fiche.recette is not None:
            raise FicheNonSure(f"une fiche « {fiche.mode} » ne doit porter aucune recette")
        return

    recette = fiche.recette
    if recette is None:
        raise FicheNonSure("fiche sans recette")
    if profil_exclu(questionnaire) is not None:
        raise FicheNonSure("dosage proposé pour un profil exclu")
    if voies_demandees is not None and recette.voie not in voies_demandees:
        raise FicheNonSure(f"voie {recette.voie} non demandée")
    if fiche.mode == "synthese" and AVERTISSEMENT_SYNTHESE not in fiche.avertissements:
        raise FicheNonSure("synthèse sans avertissement")

    for dose in recette.huiles:
        if not dose.sources:
            raise FicheNonSure(f"{dose.he_id} non tracée")
        if any(s.startswith(PREFIXE_SOURCE_TABLE) for s in dose.sources):
            raise FicheNonSure(f"{dose.he_id} tracée par la table de sécurité au lieu d'une source")
        if sources_recuperees is not None and not set(dose.sources) <= set(sources_recuperees):
            raise FicheNonSure(f"{dose.he_id} cite une source non récupérée")
        if dose.he_id in exclusions_perso:
            raise FicheNonSure(f"{dose.he_id} est dans la liste d'exclusion personnelle")
    for precaution in recette.precautions:
        if not precaution.sources:
            raise FicheNonSure(f"précaution non tracée : {precaution.texte}")
    if sources_recuperees is not None and not set(recette.sources) <= set(sources_recuperees):
        raise FicheNonSure("la recette cite une source non récupérée")

    verdict = controler_recette(
        recette,
        questionnaire,
        table,
        referentiel,
        convention_gouttes_ml=fiche.convention_gouttes_ml,
        exclusions_perso=exclusions_perso,
    )
    if not verdict.conforme:
        raise FicheNonSure("; ".join(verdict.rejets))
