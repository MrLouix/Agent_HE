"""Référentiel des huiles essentielles et normalisation des noms (spécification §3.1).

`normaliser` rapproche un nom libre (français, anglais, latin, avec ou sans chémotype)
d'un identifiant du référentiel. Un nom ambigu (ex. « Thymus vulgaris », qui désigne
plusieurs chémotypes) ou inconnu donne `None` : on ne devine jamais.
"""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import Field, StringConstraints, TypeAdapter

from agent_he.models import Modele, TexteNonVide

IdHE = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]+$")]

_PREFIXES = re.compile(r"^(huile essentielle( bio)? (de |d )?|he (de |d )?|essential oil of )")
_SUFFIXES = re.compile(r" (essential oil|oil|bio|huile essentielle)$")
_MOTS_CHEMOTYPE = re.compile(r"\b(chemotype|qt)\b")


def simplifier(texte: str) -> str:
    """Forme canonique d'un nom : minuscules, sans accents ni ponctuation, hybrides unifiés."""
    decompose = unicodedata.normalize("NFKD", texte)
    t = "".join(c for c in decompose if not unicodedata.combining(c))
    t = t.lower().replace("×", " x ")
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    # « Mentha x piperita », « Mentha × piperita » et « Mentha piperita » sont équivalents.
    t = re.sub(r"(?<=[a-z]) x (?=[a-z])", " ", t)
    t = _MOTS_CHEMOTYPE.sub("ct", t)
    t = _PREFIXES.sub("", t)
    t = _SUFFIXES.sub("", t)
    return re.sub(r" +", " ", t).strip()


class Huile(Modele):
    id: IdHE
    nom_latin: TexteNonVide
    synonymes_latins: list[str] = Field(default_factory=list)
    noms_fr: list[TexteNonVide] = Field(min_length=1)
    noms_en: list[TexteNonVide] = Field(default_factory=list)
    partie_distillee: str = ""
    chemotypes: list[str] = Field(default_factory=list)

    @property
    def nom(self) -> str:
        """Nom d'affichage (premier nom français)."""
        return self.noms_fr[0]

    def noms_latins(self) -> list[str]:
        return [self.nom_latin, *self.synonymes_latins]

    def tous_les_noms(self) -> list[str]:
        return [*self.noms_latins(), *self.noms_fr, *self.noms_en]


_LISTE_HUILES = TypeAdapter(list[Huile])


class Referentiel:
    """Index des HE, interrogeable par identifiant ou par nom libre."""

    def __init__(self, huiles: Iterable[Huile]) -> None:
        self._huiles: dict[str, Huile] = {}
        for huile in huiles:
            if huile.id in self._huiles:
                raise ValueError(f"identifiant d'HE en double : {huile.id}")
            self._huiles[huile.id] = huile
        self._index: dict[str, set[str]] = defaultdict(set)
        for huile in self._huiles.values():
            for nom in huile.tous_les_noms():
                self._index[simplifier(nom)].add(huile.id)
                for chemotype in huile.chemotypes:
                    self._index[simplifier(f"{nom} ct {chemotype}")].add(huile.id)
        # Un identifiant est aussi un nom valide (« lavande_vraie »).
        for he_id in self._huiles:
            self._index[simplifier(he_id)] = {he_id}

    @classmethod
    def depuis_fichier(cls, chemin: Path) -> "Referentiel":
        donnees = yaml.safe_load(chemin.read_text(encoding="utf-8")) or []
        return cls(_LISTE_HUILES.validate_python(donnees))

    def __contains__(self, he_id: object) -> bool:
        return he_id in self._huiles

    def __iter__(self) -> Iterator[Huile]:
        return iter(self._huiles.values())

    def __len__(self) -> int:
        return len(self._huiles)

    def get(self, he_id: str) -> Huile | None:
        return self._huiles.get(he_id)

    def __getitem__(self, he_id: str) -> Huile:
        return self._huiles[he_id]

    def candidats(self, nom: str, chemotype: str | None = None) -> set[str]:
        """Tous les identifiants auxquels le nom (et le chémotype éventuel) peut renvoyer."""
        cle = simplifier(nom)
        if chemotype:
            avec_ct = self._index.get(simplifier(f"{nom} ct {chemotype}"))
            if avec_ct:
                return set(avec_ct)
            # Chémotype non reconnu pour ce nom : on ne garde que les HE qui le déclarent.
            ct = simplifier(chemotype)
            return {
                he_id
                for he_id in self._index.get(cle, set())
                if ct in {simplifier(c) for c in self._huiles[he_id].chemotypes}
            }
        return set(self._index.get(cle, set()))

    def normaliser(self, nom: str, chemotype: str | None = None) -> str | None:
        """Identifiant de l'HE désignée par `nom`, ou `None` si inconnue ou ambiguë."""
        trouves = self.candidats(nom, chemotype)
        return next(iter(trouves)) if len(trouves) == 1 else None

    def latin_coherent(self, he_id: str, nom_latin: str) -> bool:
        """Vrai si `nom_latin` est un nom botanique accepté pour cette HE."""
        huile = self._huiles.get(he_id)
        if huile is None:
            return False
        cible = simplifier(nom_latin)
        return any(simplifier(n) == cible for n in huile.noms_latins())


def charger_referentiel(dossier_donnees: Path) -> Referentiel:
    return Referentiel.depuis_fichier(dossier_donnees / "huiles.yaml")
