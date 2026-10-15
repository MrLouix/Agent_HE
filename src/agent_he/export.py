"""Rendu Markdown d'une fiche (affichage CLI et export, spécification §10)."""

from agent_he.models import Fiche, Source
from agent_he.safety.doses import affichage
from agent_he.search.reliability import BADGES

BANDEAU = (
    "⚠️ Outil d'information, pas un avis médical. Les huiles essentielles sont des "
    "substances actives : respecte les dosages et demande conseil à un professionnel "
    "de santé en cas de doute."
)


def _nombre(valeur: float | None, suffixe: str) -> str:
    if valeur is None:
        return "—"
    return f"{valeur:g}{suffixe}".replace(".", ",")


def fiche_markdown(fiche: Fiche, sources: list[Source] | None = None) -> str:
    sources = sources or []
    lignes: list[str] = [f"> {BANDEAU}", ""]
    if fiche.mode in ("refus", "aucune"):
        titre = "⛔ Aucun dosage proposé" if fiche.mode == "refus" else "Aucune recette sûre"
        lignes += [f"## {titre}", "", fiche.motif or ""]
        if fiche.he_a_eviter:
            lignes += ["", "**HE à éviter pour ce profil :** " + ", ".join(fiche.he_a_eviter)]
        return "\n".join(lignes) + "\n"

    recette = fiche.recette
    assert recette is not None
    lignes += [f"## {recette.nom_recette}", ""]
    lignes += [f"- {b}" for b in fiche.badges]
    if fiche.avertissements:
        lignes += ["", *[f"> {a}" for a in fiche.avertissements]]
    lignes += ["", f"**Voie :** {recette.voie}"]
    if recette.base_description or recette.base_volume_ml:
        volume = f" — {_nombre(recette.base_volume_ml, ' ml')}" if recette.base_volume_ml else ""
        lignes.append(f"**Base :** {recette.base_description}{volume}")
    lignes += [
        "",
        "| HE | Nom latin | Chémotype | % | ml | gouttes* |",
        "|---|---|---|---|---|---|",
    ]
    for h in recette.huiles:
        a = affichage(h, recette.base_volume_ml, fiche.convention_gouttes_ml)
        lignes.append(
            f"| {h.nom} | *{h.nom_latin}* | {h.chemotype or '—'} | {_nombre(a.pourcentage, ' %')} "
            f"| {_nombre(a.ml, '')} | {_nombre(a.gouttes, '')} |"
        )
    lignes += ["", f"\\* calculé sur la base de {fiche.convention_gouttes_ml} gouttes/ml"]
    if recette.usage:
        lignes += ["", f"**Usage :** {recette.usage}"]
    if recette.precautions:
        lignes += ["", "### Précautions", *[f"- {p.texte}" for p in recette.precautions]]
    if fiche.contradictions:
        lignes += [
            "",
            "### Contradictions entre sources",
            *[f"- {c}" for c in fiche.contradictions],
        ]
    if fiche.rappel_journal:
        lignes += ["", f"📓 {fiche.rappel_journal}"]
    if sources:
        lignes += ["", "### Sources"]
        lignes += [f"- {BADGES[s.confiance]} [{s.titre}]({s.url})" for s in sources]
    return "\n".join(lignes) + "\n"
