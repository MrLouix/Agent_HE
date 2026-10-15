"""Table de sécurité : chargement, contrôles et application (règle `regle-table-securite.md`).

Points clés de la règle :
- une entrée = une valeur, citation obligatoire (P1, P2) ;
- un plafond n'est appliqué que s'il est `valide` avec une empreinte correcte ; un drapeau
  ou une contre-indication s'applique dès sa saisie (P5, §6) ;
- l'empreinte SHA-256 des champs de fond rend visible toute modification (§7) ;
- les contrôles du §9 sont exposés par `controler`, bloquants en CI.
"""

import hashlib
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import Field, StringConstraints, TypeAdapter, model_validator

from agent_he.models import Drapeau, Modele, TexteNonVide, TrancheAge, Voie
from agent_he.referentiel.huiles import Referentiel

TOUTES_HE = "*"


class TypeEntree(StrEnum):
    PLAFOND = "plafond"
    PLAFOND_TOTAL = "plafond_total"
    DRAPEAU = "drapeau"
    INTERDIT_PROFIL = "interdit_profil"


class Statut(StrEnum):
    BROUILLON = "brouillon"
    VERIFIE = "verifie"
    VALIDE = "valide"
    RETIRE = "retire"


class ProfilRisque(StrEnum):
    """Profils visés par une entrée `interdit_profil` (hors tranches d'âge)."""

    GROSSESSE_ALLAITEMENT = "grossesse_allaitement"
    EPILEPSIE = "epilepsie"
    ASTHME = "asthme"
    TRAITEMENT = "traitement"
    PATHOLOGIE_HORMONALE = "pathologie_hormonale"


Profil = ProfilRisque | TrancheAge
IdEntree = Annotated[str, StringConstraints(pattern=r"^SEC-\d{4,}$")]


class SourceSecurite(Modele):
    ouvrage: TexteNonVide
    page: int | str
    localisation: TexteNonVide
    citation: TexteNonVide


class Saisie(Modele):
    par: TexteNonVide
    le: date
    methode: Literal["manuelle", "assistee"]


class Verification(Modele):
    par: str | None = None
    le: date | None = None
    resultat: Literal["conforme", "non_conforme"] | None = None
    commentaire: str | None = None
    empreinte: str | None = None


class Validation(Modele):
    par: str | None = None
    le: date | None = None
    empreinte: str | None = None


class EntreeSecurite(Modele):
    """Une ligne de `data/securite.yaml` (règle §4)."""

    id: IdEntree
    type: TypeEntree
    he_id: TexteNonVide
    nom_latin: str | None = None
    chemotype: str | None = None
    voie: Voie | None = None
    population: TrancheAge | None = None
    valeur: float | None = Field(default=None, gt=0)
    unite: str | None = None
    base_pourcentage: Literal["p/p", "v/v"] | None = None
    drapeau: Drapeau | None = None
    profil: Profil | None = None
    detail: str | None = None
    source: SourceSecurite
    interpretation: str | None = None
    saisie: Saisie
    verification: Verification = Field(default_factory=Verification)
    validation: Validation = Field(default_factory=Validation)
    statut: Statut = Statut.BROUILLON
    motif_retrait: str | None = None

    @model_validator(mode="after")
    def _champs_par_type(self) -> "EntreeSecurite":
        manquants: list[str] = []
        if self.he_id != TOUTES_HE and not self.nom_latin:
            manquants.append("nom_latin")
        if self.type in (TypeEntree.PLAFOND, TypeEntree.PLAFOND_TOTAL):
            for champ in ("voie", "population", "valeur", "unite"):
                if getattr(self, champ) is None:
                    manquants.append(champ)
            if self.unite == "%" and self.valeur is not None and self.valeur > 100:
                raise ValueError(f"{self.id} : un pourcentage ne peut pas dépasser 100")
        if self.type == TypeEntree.PLAFOND_TOTAL and self.he_id != TOUTES_HE:
            raise ValueError(f"{self.id} : un plafond_total porte he_id « * »")
        if self.type == TypeEntree.PLAFOND and self.he_id == TOUTES_HE:
            raise ValueError(f"{self.id} : un plafond porte sur une HE précise")
        if self.type == TypeEntree.DRAPEAU:
            if self.drapeau is None:
                manquants.append("drapeau")
            elif self.drapeau == Drapeau.INTERACTION_MEDICAMENT and not self.detail:
                manquants.append("detail")
        if self.type == TypeEntree.INTERDIT_PROFIL and self.profil is None:
            manquants.append("profil")
        if manquants:
            raise ValueError(f"{self.id} ({self.type}) : champs manquants {manquants}")
        return self

    @property
    def autorise(self) -> bool:
        """Vrai pour une entrée qui autorise un dosage (plafond), faux si elle restreint."""
        return self.type in (TypeEntree.PLAFOND, TypeEntree.PLAFOND_TOTAL)


_CHAMPS_DE_FOND = (
    "type",
    "he_id",
    "nom_latin",
    "chemotype",
    "voie",
    "population",
    "valeur",
    "unite",
    "base_pourcentage",
    "drapeau",
    "profil",
    "detail",
    "source",
    "interpretation",
)


def empreinte(entree: EntreeSecurite) -> str:
    """SHA-256 des champs de fond (règle §7), indépendante des champs de suivi."""
    donnees = entree.model_dump(mode="json", include=set(_CHAMPS_DE_FOND))
    canonique = json.dumps(donnees, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonique.encode("utf-8")).hexdigest()


# --- État effectif (règle §6) -------------------------------------------------------


@dataclass(frozen=True)
class EtatEffectif:
    applique: bool
    valide: bool
    """Vrai si l'entrée est validée avec une empreinte correcte."""
    alerte: str | None = None


def etat_effectif(entree: EntreeSecurite) -> EtatEffectif:
    if entree.statut == Statut.RETIRE:
        return EtatEffectif(applique=False, valide=False)
    alerte: str | None = None
    valide = False
    if entree.statut == Statut.VALIDE:
        attendue = empreinte(entree)
        if entree.validation.empreinte == attendue and entree.verification.empreinte == attendue:
            valide = True
        else:
            alerte = f"{entree.id} : empreinte invalide, entrée modifiée depuis sa validation"
    elif entree.statut == Statut.VERIFIE and entree.verification.empreinte != empreinte(entree):
        alerte = f"{entree.id} : entrée modifiée depuis sa vérification, traitée comme brouillon"
    if entree.autorise:
        return EtatEffectif(applique=valide, valide=valide, alerte=alerte)
    if not valide and alerte is None:
        alerte = f"{entree.id} : non validé"
    return EtatEffectif(applique=True, valide=valide, alerte=alerte)


# --- Contrôles automatiques (règle §9) -----------------------------------------------


def controler(entrees: Iterable[EntreeSecurite], referentiel: Referentiel) -> list[str]:
    """Problèmes bloquants de la table ; une liste vide signifie « table conforme »."""
    problemes: list[str] = []
    vus: set[str] = set()
    for e in entrees:
        if e.id in vus:
            problemes.append(f"{e.id} : identifiant en double")
        vus.add(e.id)

        if e.he_id != TOUTES_HE:
            if e.he_id not in referentiel:
                problemes.append(f"{e.id} : HE inconnue du référentiel ({e.he_id})")
            elif e.nom_latin and not referentiel.latin_coherent(e.he_id, e.nom_latin):
                problemes.append(f"{e.id} : nom latin « {e.nom_latin} » incohérent avec {e.he_id}")

        v, val = e.verification, e.validation
        if e.statut in (Statut.VERIFIE, Statut.VALIDE):
            if not (v.par and v.le and v.empreinte) or v.resultat != "conforme":
                problemes.append(f"{e.id} : statut {e.statut} sans vérification conforme")
            if e.autorise and e.unite != "%":
                problemes.append(f"{e.id} : unité « {e.unite} » non applicable (R12)")
        if e.statut == Statut.VALIDE:
            attendue = empreinte(e)
            if not (val.par and val.le and val.empreinte):
                problemes.append(f"{e.id} : statut valide sans validation renseignée")
            elif val.empreinte != v.empreinte or val.empreinte != attendue:
                problemes.append(f"{e.id} : empreinte de validation incorrecte")

        if v.le is not None and v.le < e.saisie.le:
            problemes.append(f"{e.id} : vérification antérieure à la saisie")
        if val.le is not None and (v.le is None or val.le < v.le):
            problemes.append(f"{e.id} : validation antérieure à la vérification")
        if e.statut == Statut.RETIRE and not e.motif_retrait:
            problemes.append(f"{e.id} : retrait sans motif")
    return problemes


# --- Table appliquée -----------------------------------------------------------------


@dataclass(frozen=True)
class Restriction:
    """Drapeau ou contre-indication applicable, avec son niveau de validation."""

    entree_id: str
    he_id: str
    valide: bool
    drapeau: Drapeau | None = None
    profil: Profil | None = None
    detail: str | None = None


_LISTE_ENTREES = TypeAdapter(list[EntreeSecurite])


class TableSecurite:
    """Vue applicable de la table : seules les entrées effectives sont consultées."""

    def __init__(self, entrees: Iterable[EntreeSecurite]) -> None:
        self.entrees: list[EntreeSecurite] = list(entrees)
        self.alertes: list[str] = []
        self._plafonds: list[EntreeSecurite] = []
        self._restrictions: list[Restriction] = []
        for e in self.entrees:
            etat = etat_effectif(e)
            if etat.alerte:
                self.alertes.append(etat.alerte)
            if not etat.applique:
                continue
            if e.autorise:
                # R12 : seul un pourcentage dans le produit final est exploitable.
                if e.unite == "%":
                    self._plafonds.append(e)
            else:
                self._restrictions.append(
                    Restriction(
                        entree_id=e.id,
                        he_id=e.he_id,
                        valide=etat.valide,
                        drapeau=e.drapeau,
                        profil=e.profil,
                        detail=e.detail,
                    )
                )

    @classmethod
    def depuis_fichier(cls, chemin: Path) -> "TableSecurite":
        return cls(lire_entrees(chemin))

    def __iter__(self) -> Iterator[EntreeSecurite]:
        return iter(self.entrees)

    def connait(self, he_id: str) -> bool:
        """Vrai si au moins une entrée effective porte sur cette HE."""
        return any(e.he_id == he_id for e in self._plafonds) or any(
            r.he_id == he_id for r in self._restrictions
        )

    def plafond(
        self, he_id: str, voie: Voie, population: TrancheAge, chemotype: str | None = None
    ) -> float | None:
        """Plafond validé le plus restrictif (R3, R11), ou `None` (fail closed)."""
        valeurs = [
            e.valeur
            for e in self._plafonds
            if e.type == TypeEntree.PLAFOND
            and e.he_id == he_id
            and e.voie == voie
            and e.population == population
            and e.valeur is not None
            and (e.chemotype is None or e.chemotype == chemotype)
        ]
        return min(valeurs) if valeurs else None

    def plafond_total(self, voie: Voie, population: TrancheAge) -> float | None:
        valeurs = [
            e.valeur
            for e in self._plafonds
            if e.type == TypeEntree.PLAFOND_TOTAL
            and e.voie == voie
            and e.population == population
            and e.valeur is not None
        ]
        return min(valeurs) if valeurs else None

    def plafond_effectif(
        self, he_id: str, voie: Voie, population: TrancheAge, chemotype: str | None = None
    ) -> float | None:
        """Plafond par HE, sinon plafond total de la voie (R8) ; `None` ⇒ pas de dosage."""
        propre = self.plafond(he_id, voie, population, chemotype)
        total = self.plafond_total(voie, population)
        if propre is None:
            return total
        return propre if total is None else min(propre, total)

    def restrictions(self, he_id: str) -> list[Restriction]:
        return [r for r in self._restrictions if r.he_id in (he_id, TOUTES_HE)]

    def drapeaux(self, he_id: str) -> set[Drapeau]:
        return {r.drapeau for r in self.restrictions(he_id) if r.drapeau is not None}

    def he_avec_drapeau(self, drapeau: Drapeau) -> set[str]:
        return {r.he_id for r in self._restrictions if r.drapeau == drapeau}

    def he_interdites(self, profil: Profil) -> set[str]:
        return {r.he_id for r in self._restrictions if r.profil == profil}

    def profils_interdits(self, he_id: str) -> set[Profil]:
        return {r.profil for r in self.restrictions(he_id) if r.profil is not None}


def lire_entrees(chemin: Path) -> list[EntreeSecurite]:
    donnees = yaml.safe_load(chemin.read_text(encoding="utf-8")) or []
    return _LISTE_ENTREES.validate_python(donnees)


def ecrire_entrees(chemin: Path, entrees: Iterable[EntreeSecurite], entete: str = "") -> None:
    donnees: list[dict[str, Any]] = [e.model_dump(mode="json") for e in entrees]
    corps = yaml.safe_dump(donnees, allow_unicode=True, sort_keys=False, width=100)
    chemin.write_text(entete + corps, encoding="utf-8")


def entete_fichier(chemin: Path) -> str:
    """Commentaires de tête du fichier, conservés lors d'une réécriture."""
    lignes: list[str] = []
    for ligne in chemin.read_text(encoding="utf-8").splitlines(keepends=True):
        if ligne.startswith("#") or not ligne.strip():
            lignes.append(ligne)
        else:
            break
    return "".join(lignes)


def charger_table(dossier_donnees: Path) -> TableSecurite:
    return TableSecurite.depuis_fichier(dossier_donnees / "securite.yaml")


# --- Cycle de vie (règle §6, §7) ----------------------------------------------------


class ErreurCycle(ValueError):
    """Transition de statut refusée."""


def verifier(
    entree: EntreeSecurite,
    par: str,
    le: date,
    conforme: bool,
    commentaire: str | None = None,
) -> EntreeSecurite:
    """Enregistre une vérification ; renvoie une nouvelle entrée."""
    if entree.statut == Statut.RETIRE:
        raise ErreurCycle(f"{entree.id} : entrée retirée")
    if le < entree.saisie.le:
        raise ErreurCycle(f"{entree.id} : vérification antérieure à la saisie")
    if par == entree.saisie.par and le == entree.saisie.le:
        raise ErreurCycle(
            f"{entree.id} : la vérification doit avoir lieu lors d'une session distincte "
            "de la saisie (autre personne ou autre date)"
        )
    if not conforme and not commentaire:
        raise ErreurCycle(f"{entree.id} : un résultat non conforme exige un commentaire")
    verification = Verification(
        par=par,
        le=le,
        resultat="conforme" if conforme else "non_conforme",
        commentaire=commentaire,
        empreinte=empreinte(entree),
    )
    return entree.model_copy(
        update={
            "verification": verification,
            "validation": Validation(),
            "statut": Statut.VERIFIE if conforme else Statut.BROUILLON,
        }
    )


def valider(entree: EntreeSecurite, par: str, le: date) -> EntreeSecurite:
    """Valide exactement ce qui a été vérifié ; renvoie une nouvelle entrée."""
    v = entree.verification
    if entree.statut != Statut.VERIFIE:
        raise ErreurCycle(f"{entree.id} : seule une entrée « verifie » peut être validée")
    if v.resultat != "conforme" or v.le is None:
        raise ErreurCycle(f"{entree.id} : vérification non conforme")
    if v.empreinte != empreinte(entree):
        raise ErreurCycle(f"{entree.id} : entrée modifiée depuis sa vérification")
    if le < v.le:
        raise ErreurCycle(f"{entree.id} : validation antérieure à la vérification")
    if entree.autorise and entree.unite != "%":
        raise ErreurCycle(f"{entree.id} : unité « {entree.unite} » non applicable (R12)")
    return entree.model_copy(
        update={
            "validation": Validation(par=par, le=le, empreinte=v.empreinte),
            "statut": Statut.VALIDE,
        }
    )
