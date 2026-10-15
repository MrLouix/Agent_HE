"""Priorité 1 : correspondance avec une recette existante (spécification §6).

Filtres stricts (besoin, voie) par l'index, similarité ≥ seuil, puis contrôles communs
(profil, exclusions, plafonds). 1a (corpus) passe toujours avant 1b (web).
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field

from agent_he.kb.corpus import RecetteCorpus
from agent_he.kb.store import Magasin
from agent_he.models import Besoin, Demande, Recette
from agent_he.referentiel.huiles import Referentiel
from agent_he.referentiel.securite import TableSecurite
from agent_he.safety.checks import IndicationSource, controler_recette


@dataclass
class Candidate:
    """Recette conforme, prête à être présentée."""

    recette: Recette
    mode: str
    pertinence: float = 1.0
    ref: str | None = None
    """Identifiant stable de la recette (corpus) pour le journal et les favoris."""
    contradictions: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    controles: list[str] = field(default_factory=list)


@dataclass
class Contexte:
    """Ce dont les contrôles ont besoin, partagé par toutes les étapes."""

    demande: Demande
    table: TableSecurite
    referentiel: Referentiel
    convention_gouttes_ml: int
    exclusions_perso: Mapping[str, str] | Collection[str] = ()
    notes: list[str] = field(default_factory=list)
    controles: list[str] = field(default_factory=list)

    def controler(
        self,
        recette: Recette,
        mode: str,
        pertinence: float = 1.0,
        ref: str | None = None,
        indications: Sequence[IndicationSource] = (),
    ) -> Candidate | None:
        verdict = controler_recette(
            recette,
            self.demande.questionnaire,
            self.table,
            self.referentiel,
            convention_gouttes_ml=self.convention_gouttes_ml,
            exclusions_perso=self.exclusions_perso,
            indications=indications,
        )
        self.controles.extend(verdict.controles)
        if not verdict.conforme or verdict.recette is None:
            self.notes.extend(f"« {recette.nom_recette} » rejetée : {r}" for r in verdict.rejets)
            return None
        return Candidate(
            recette=verdict.recette,
            mode=mode,
            pertinence=pertinence,
            ref=ref,
            contradictions=verdict.contradictions,
            avertissements=verdict.avertissements,
            controles=verdict.controles,
        )


def correspondances_corpus(
    contexte: Contexte,
    magasin: Magasin,
    corpus: Mapping[str, RecetteCorpus],
    besoins: Sequence[Besoin],
    texte: str,
    seuil: float,
) -> list[Candidate]:
    """Priorité 1a : recettes validées proches du besoin, conformes."""
    candidates: list[Candidate] = []
    for correspondance in magasin.chercher(texte, contexte.demande.voies, besoins):
        entree = corpus.get(correspondance.id)
        if entree is None or correspondance.similarite < seuil:
            continue
        candidate = contexte.controler(
            entree.recette, "validee", correspondance.similarite, ref=entree.id
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates
