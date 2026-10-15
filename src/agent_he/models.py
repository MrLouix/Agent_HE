"""Modèles de données de l'agent (plan §3, spécification §6, §8 et §11).

Les invariants de sécurité exprimables au niveau des types sont vérifiés ici :
la voie orale n'existe pas, une fiche de refus ne porte aucune recette, une synthèse
porte toujours l'avertissement IA. Les contrôles qui dépendent des données de
référence (plafonds, drapeaux, traçabilité) relèvent du module `safety`.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    computed_field,
    model_validator,
)

AVERTISSEMENT_SYNTHESE = (
    "⚠️ Mélange synthétisé par l'IA à partir des sources listées — vérifie les dosages "
    "avec un professionnel de santé avant utilisation."
)

TexteNonVide = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Note = Annotated[int, Field(ge=1, le=5)]


def _maintenant() -> datetime:
    return datetime.now(UTC)


class Modele(BaseModel):
    """Base commune : tout champ inconnu est refusé."""

    model_config = ConfigDict(extra="forbid")


# --- Énumérations ---------------------------------------------------------------


class Voie(StrEnum):
    """Voies d'administration. La voie orale est volontairement absente (spec §0)."""

    DIFFUSION = "diffusion"
    CUTANEE = "cutanee"
    BAIN = "bain"
    MASSAGE = "massage"
    INHALATION = "inhalation"


class TrancheAge(StrEnum):
    MOINS_3 = "moins_3"
    DE_3_A_6 = "de_3_a_6"
    DE_6_A_12 = "de_6_a_12"
    DE_12_A_18 = "de_12_a_18"
    ADULTE = "adulte"
    PLUS_65 = "plus_65"


class Confiance(StrEnum):
    """Niveaux de confiance des sources (spec §4)."""

    INSTITUTIONNEL = "institutionnel"
    REFERENCE_SECURITE = "reference_securite"
    COMMERCIAL = "commercial"
    NON_VERIFIE = "non_verifie"


class Drapeau(StrEnum):
    """Drapeaux de risque de la table de sécurité (spec §3.2)."""

    PHOTOTOXIQUE = "phototoxique"
    DERMOCAUSTIQUE = "dermocaustique"
    NEUROTOXIQUE = "neurotoxique"
    HORMONE_LIKE = "hormone_like"
    ALLERGENE = "allergene"
    INTERACTION_MEDICAMENT = "interaction_medicament"


class Tolerance(StrEnum):
    AUCUNE = "aucune"
    LEGERE = "legere"
    FORTE = "forte"


ModeFiche = Literal["validee", "publiee", "synthese", "refus", "aucune"]
MODES_AVEC_RECETTE: frozenset[str] = frozenset({"validee", "publiee", "synthese"})


# --- Demande ----------------------------------------------------------------------


class Questionnaire(Modele):
    """Questionnaire de sécurité, portant sur la personne concernée (spec §8)."""

    age: TrancheAge
    grossesse_allaitement: bool = False
    epilepsie: bool = False
    asthme: bool = False
    traitement: bool = False
    allergies: bool = False
    pathologie_hormonale: bool = False


class Demande(Modele):
    besoin: TexteNonVide
    voies: list[Voie] = Field(min_length=1)
    texte_libre: str = ""
    questionnaire: Questionnaire


# --- Sources et recettes ----------------------------------------------------------


class Source(Modele):
    url: HttpUrl
    titre: str
    confiance: Confiance
    extrait: str = ""
    date_recuperation: datetime = Field(default_factory=_maintenant)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def domaine(self) -> str:
        hote = (self.url.host or "").lower()
        return hote.removeprefix("www.")


class Quantite(Modele):
    valeur: float = Field(gt=0)
    unite: Literal["gouttes", "ml", "%"]

    @model_validator(mode="after")
    def _pourcentage_borne(self) -> "Quantite":
        if self.unite == "%" and self.valeur > 100:
            raise ValueError("un pourcentage ne peut pas dépasser 100")
        return self


class DoseHE(Modele):
    he_id: TexteNonVide
    nom: TexteNonVide
    nom_latin: TexteNonVide
    chemotype: str | None = None
    quantite: Quantite
    concentration_pct: float | None = Field(default=None, gt=0, le=100)
    """Calculée par le code (spec §7), jamais fournie par le LLM."""
    sources: list[str] = Field(default_factory=list)


class Precaution(Modele):
    texte: TexteNonVide
    sources: list[str] = Field(default_factory=list)


class Recette(Modele):
    nom_recette: TexteNonVide
    voie: Voie
    huiles: list[DoseHE] = Field(min_length=1)
    base_description: str = ""
    base_volume_ml: float | None = Field(default=None, gt=0)
    usage: str = ""
    precautions: list[Precaution] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class Fiche(Modele):
    """Fiche présentée à l'utilisateur (spec §6, §10)."""

    mode: ModeFiche
    recette: Recette | None = None
    motif: str | None = None
    """Explication obligatoire pour un refus ou l'absence de recette sûre."""
    badges: list[str] = Field(default_factory=list)
    avertissements: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    he_a_eviter: list[str] = Field(default_factory=list)
    convention_gouttes_ml: int = Field(gt=0, le=100)
    rappel_journal: str | None = None

    @model_validator(mode="after")
    def _coherence_mode(self) -> "Fiche":
        if self.mode in MODES_AVEC_RECETTE:
            if self.recette is None:
                raise ValueError(f"une fiche en mode « {self.mode} » doit porter une recette")
        else:
            if self.recette is not None:
                raise ValueError(f"une fiche en mode « {self.mode} » ne doit porter aucune recette")
            if not self.motif:
                raise ValueError(f"une fiche en mode « {self.mode} » doit expliquer son motif")
        if self.mode == "synthese" and AVERTISSEMENT_SYNTHESE not in self.avertissements:
            self.avertissements.insert(0, AVERTISSEMENT_SYNTHESE)
        return self


# --- Produits ---------------------------------------------------------------------


class Produit(Modele):
    boutique: TexteNonVide
    nom: TexteNonVide
    nom_latin: str | None = None
    chemotype: str | None = None
    origine: str | None = None
    labels: list[str] = Field(default_factory=list)
    volume_ml: float = Field(gt=0)
    prix: float = Field(ge=0)
    url: HttpUrl
    date_releve: datetime = Field(default_factory=_maintenant)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def prix_ml(self) -> float:
        return self.prix / self.volume_ml


# --- Journal d'audit --------------------------------------------------------------


class EntreeAudit(Modele):
    id: UUID = Field(default_factory=uuid4)
    horodatage: datetime = Field(default_factory=_maintenant)
    demande: Demande
    sources: list[str] = Field(default_factory=list)
    mode: ModeFiche
    controles_declenches: list[str] = Field(default_factory=list)


# --- Journal d'usage (spec §11) ---------------------------------------------------


class EntreeUsage(Modele):
    id: UUID = Field(default_factory=uuid4)
    horodatage: datetime = Field(default_factory=_maintenant)
    recette_ref: str | None = None
    melange_libre: list[DoseHE] | None = None
    voie: Voie
    personne: TexteNonVide = "moi"
    efficacite: Note | None = None
    """De 1 à 5 ; `None` signifie « sans objet » (usage plaisir)."""
    tolerance: Tolerance
    description_reaction: str | None = None
    odeur: Note | None = None
    contexte: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _une_seule_recette(self) -> "EntreeUsage":
        if (self.recette_ref is None) == (self.melange_libre is None):
            raise ValueError("indiquer soit une recette de référence, soit un mélange libre")
        if self.melange_libre is not None and not self.melange_libre:
            raise ValueError("un mélange libre doit contenir au moins une huile")
        return self


class ExclusionPerso(Modele):
    he_id: TexteNonVide
    date_ajout: datetime = Field(default_factory=_maintenant)
    motif: TexteNonVide
    entrees_liees: list[UUID] = Field(default_factory=list)


class StatsHE(Modele):
    he_id: TexteNonVide
    nb_usages: int = Field(ge=0)
    efficacite_moy: float | None = Field(default=None, ge=1, le=5)
    odeur_moy: float | None = Field(default=None, ge=1, le=5)
    nb_reactions_legeres: int = Field(default=0, ge=0)
    nb_reactions_fortes: int = Field(default=0, ge=0)
