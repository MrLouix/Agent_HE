"""Priorité 2 : synthèse tracée (spécification §6).

Le LLM ne reçoit que les HE et concentrations déjà extraites, normalisées et tracées
(jamais les pages brutes). Il sélectionne ; le code calcule les quantités :
- la concentration de départ est celle d'une source ; si plusieurs sources donnent une
  concentration pour la même HE et la même voie, la plus faible l'emporte (contradiction) ;
- elle est plafonnée au plafond effectif de la table (§7), puis convertie en ml pour le
  volume de base ;
- toute HE ou source proposée par le LLM hors de ce réservoir est ignorée.
"""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from agent_he.llm.base import LLM, ErreurLLM
from agent_he.llm.prompts import messages_synthese
from agent_he.models import DoseHE, Recette, TrancheAge, Voie
from agent_he.referentiel.securite import TableSecurite
from agent_he.safety.doses import concentration_pct, dose_pour_concentration


@dataclass(frozen=True)
class DoseSource:
    """Concentration d'une HE relevée dans une source (déjà tracée)."""

    he_id: str
    nom: str
    nom_latin: str
    voie: Voie
    concentration_pct: float
    source: str


def reservoir(recettes: Iterable[Recette], convention_gouttes_ml: int) -> list[DoseSource]:
    """Concentrations calculables des recettes tracées."""
    doses: list[DoseSource] = []
    for recette in recettes:
        for h in recette.huiles:
            pct = concentration_pct(h.quantite, recette.base_volume_ml, convention_gouttes_ml)
            if pct is None:
                continue
            for source in h.sources:
                doses.append(DoseSource(h.he_id, h.nom, h.nom_latin, recette.voie, pct, source))
    return doses


class ChoixHE(BaseModel):
    model_config = ConfigDict(extra="ignore")

    he_id: str
    source: str


class SelectionSynthese(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nom_recette: str = "Synergie synthétisée"
    huiles: list[ChoixHE] = Field(default_factory=list)
    usage: str = ""


@dataclass
class Synthese:
    recette: Recette | None
    notes: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)


def synthetiser(
    llm: LLM,
    besoin: str,
    voie: Voie,
    doses: list[DoseSource],
    table: TableSecurite,
    population: TrancheAge,
    *,
    volume_ml: float,
    convention_gouttes_ml: int,
    max_huiles: int = 4,
    plafonds_sources: Mapping[str, float] | None = None,
) -> Synthese:
    """`plafonds_sources` : dosages maximaux relevés dans les sources (règle de contradiction)."""
    pool = [d for d in doses if d.voie == voie]
    if not pool:
        return Synthese(None, [f"Synthèse impossible : aucune dose source pour la voie {voie}"])
    donnees = json.dumps(
        [
            {
                "he_id": d.he_id,
                "nom": d.nom,
                "concentration_pct": d.concentration_pct,
                "source": d.source,
            }
            for d in pool
        ],
        ensure_ascii=False,
    )
    try:
        selection = llm.complete(messages_synthese(besoin, str(voie), donnees), SelectionSynthese)
    except ErreurLLM as exc:
        return Synthese(None, [f"Synthèse impossible : {exc}"])

    notes: list[str] = []
    contradictions: list[str] = []
    huiles: list[DoseHE] = []
    vues: set[str] = set()
    for choix in selection.huiles:
        candidates = [d for d in pool if d.he_id == choix.he_id]
        if not candidates or not any(d.source == choix.source for d in candidates):
            notes.append(f"Synthèse : {choix.he_id} ignorée (absente des sources fournies)")
            continue
        if choix.he_id in vues or len(huiles) >= max_huiles:
            continue
        vues.add(choix.he_id)
        concentrations = {d.concentration_pct for d in candidates}
        pct = min(concentrations)
        retenue = [d for d in candidates if d.concentration_pct == pct]
        if len(concentrations) > 1:
            contradictions.append(
                f"{candidates[0].nom} : concentrations divergentes selon les sources "
                f"({', '.join(f'{c:g} %' for c in sorted(concentrations))}) ; "
                f"la plus faible ({pct:g} %) est retenue."
            )
        plafond = table.plafond_effectif(choix.he_id, voie, population)
        if plafond is not None and plafonds_sources and choix.he_id in plafonds_sources:
            plafond = min(plafond, plafonds_sources[choix.he_id])
        if plafond is not None and pct > plafond:
            notes.append(f"{candidates[0].nom} : {pct:g} % ramenée au plafond de {plafond:g} %")
            pct = plafond
        quantite = dose_pour_concentration(pct, volume_ml, convention_gouttes_ml)
        if quantite.valeur <= 0:
            continue
        huiles.append(
            DoseHE(
                he_id=choix.he_id,
                nom=candidates[0].nom,
                nom_latin=candidates[0].nom_latin,
                quantite=quantite,
                concentration_pct=pct,
                sources=sorted({d.source for d in retenue}),
            )
        )
    if not huiles:
        return Synthese(None, [*notes, "Synthèse impossible : aucune HE retenue"], contradictions)
    recette = Recette(
        nom_recette=selection.nom_recette.strip() or "Synergie synthétisée",
        voie=voie,
        huiles=huiles,
        base_description="huile végétale ou base neutre",
        base_volume_ml=volume_ml,
        usage=selection.usage,
        sources=sorted({s for h in huiles for s in h.sources}),
    )
    return Synthese(recette, notes, contradictions)
