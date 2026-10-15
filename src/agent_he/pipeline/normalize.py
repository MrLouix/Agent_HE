"""Normalisation (code) : recettes brutes ⇒ `Recette` rattachées au référentiel (spec §5).

Une HE non reconnue (ou ambiguë) est exclue ; une URL qui ne fait pas partie des
résultats récupérés est ignorée ; une voie orale ou inconnue rejette la recette.
"""

from collections.abc import Collection
from dataclasses import dataclass, field

from agent_he.models import DoseHE, Precaution, Quantite, Recette, Voie
from agent_he.pipeline.extract import HuileBrute, IndicationBrute, RecetteBrute
from agent_he.referentiel.huiles import Referentiel, simplifier
from agent_he.safety.checks import IndicationSource

_VOIES: dict[str, Voie] = {
    "diffusion": Voie.DIFFUSION,
    "diffuseur": Voie.DIFFUSION,
    "diffusion atmospherique": Voie.DIFFUSION,
    "cutanee": Voie.CUTANEE,
    "voie cutanee": Voie.CUTANEE,
    "application cutanee": Voie.CUTANEE,
    "topique": Voie.CUTANEE,
    "peau": Voie.CUTANEE,
    "bain": Voie.BAIN,
    "massage": Voie.MASSAGE,
    "inhalation": Voie.INHALATION,
    "inhalation seche": Voie.INHALATION,
    "olfaction": Voie.INHALATION,
}
_UNITES: dict[str, str] = {
    "goutte": "gouttes",
    "gouttes": "gouttes",
    "gtt": "gouttes",
    "drop": "gouttes",
    "drops": "gouttes",
    "ml": "ml",
    "millilitre": "ml",
    "millilitres": "ml",
    "%": "%",
    "pourcent": "%",
    "pour cent": "%",
}
_PROFILS: list[tuple[str, str]] = [
    ("grossesse", "grossesse_allaitement"),
    ("enceinte", "grossesse_allaitement"),
    ("allait", "grossesse_allaitement"),
    ("epilep", "epilepsie"),
    ("asthm", "asthme"),
    ("anticoag", "traitement"),
    ("medicament", "traitement"),
    ("traitement", "traitement"),
    ("hormon", "pathologie_hormonale"),
]


def normaliser_voie(texte: str) -> Voie | None:
    return _VOIES.get(simplifier(texte))


def normaliser_unite(texte: str) -> str | None:
    t = texte.strip().lower()
    return _UNITES.get(t) or _UNITES.get(simplifier(t))


def normaliser_profil(texte: str) -> str | None:
    t = simplifier(texte)
    return next((profil for cle, profil in _PROFILS if cle in t), None)


def identifier(huile: HuileBrute | IndicationBrute, referentiel: Referentiel) -> str | None:
    """Identifiant du référentiel, par le nom latin d'abord, puis par le nom usuel."""
    chemotype = getattr(huile, "chemotype", None)
    for nom in (huile.nom_latin, huile.nom):
        if nom:
            he_id = referentiel.normaliser(nom, chemotype)
            if he_id is not None:
                return he_id
    return None


@dataclass
class Normalisation:
    recette: Recette | None
    notes: list[str] = field(default_factory=list)
    huiles_exclues: bool = False
    """Vrai si au moins une HE de la recette brute a été exclue (recette plus verbatim)."""


def normaliser_recette(
    brute: RecetteBrute, referentiel: Referentiel, urls_recuperees: Collection[str]
) -> Normalisation:
    notes: list[str] = []
    voie = normaliser_voie(brute.voie)
    if voie is None:
        return Normalisation(None, [f"« {brute.nom_recette} » écartée : voie « {brute.voie} »"])

    huiles: list[DoseHE] = []
    for h in brute.huiles:
        he_id = identifier(h, referentiel)
        unite = normaliser_unite(h.quantite.unite)
        if he_id is None:
            notes.append(f"HE « {h.nom} » non reconnue : exclue")
            continue
        if unite is None or h.quantite.valeur <= 0 or (unite == "%" and h.quantite.valeur > 100):
            notes.append(f"{h.nom} : quantité « {h.quantite.valeur} {h.quantite.unite} » exclue")
            continue
        if h.source not in urls_recuperees:
            notes.append(f"{h.nom} : source non récupérée ({h.source}) : exclue")
            continue
        huile = referentiel[he_id]
        chemotype = h.chemotype if h.chemotype and h.chemotype in huile.chemotypes else None
        huiles.append(
            DoseHE(
                he_id=he_id,
                nom=huile.nom,
                nom_latin=huile.nom_latin,
                chemotype=chemotype,
                quantite=Quantite(valeur=h.quantite.valeur, unite=unite),  # type: ignore[arg-type]
                sources=[h.source],
            )
        )
    exclues = len(huiles) < len(brute.huiles)
    if not huiles:
        return Normalisation(None, [*notes, f"« {brute.nom_recette} » : aucune HE retenue"], True)

    precautions = [
        Precaution(texte=p.texte, sources=[p.source])
        for p in brute.precautions
        if p.texte.strip() and p.source in urls_recuperees
    ]
    sources = sorted({h.sources[0] for h in huiles} | ({brute.source} & set(urls_recuperees)))
    recette = Recette(
        nom_recette=brute.nom_recette.strip() or "Recette",
        voie=voie,
        huiles=huiles,
        base_description=brute.base_description,
        base_volume_ml=brute.base_volume_ml
        if brute.base_volume_ml and brute.base_volume_ml > 0
        else None,
        usage=brute.usage,
        precautions=precautions,
        sources=sources,
    )
    return Normalisation(recette, notes, exclues)


def normaliser_indication(
    brute: IndicationBrute, referentiel: Referentiel, urls_recuperees: Collection[str]
) -> IndicationSource | None:
    if brute.source not in urls_recuperees:
        return None
    he_id = identifier(brute, referentiel)
    if he_id is None:
        return None
    if brute.type == "plafond":
        if brute.valeur is None or brute.unite is None or normaliser_unite(brute.unite) != "%":
            return None
        voie = normaliser_voie(brute.voie) if brute.voie else None
        return IndicationSource(
            he_id=he_id, type="plafond", voie=voie, valeur=brute.valeur, source=brute.source
        )
    profil = normaliser_profil(brute.profil or "")
    if profil is None:
        return None
    return IndicationSource(
        he_id=he_id, type="contre_indication", profil=profil, source=brute.source
    )
