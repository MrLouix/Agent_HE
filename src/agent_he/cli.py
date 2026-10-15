"""Interface en ligne de commande `agent-he`."""

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from agent_he import services
from agent_he.config import Settings, get_settings
from agent_he.export import fiche_markdown
from agent_he.kb.ingest import reindexer
from agent_he.kb.store import Magasin
from agent_he.kb.validation import ErreurValidation, FileValidation
from agent_he.models import Besoin, Demande, Questionnaire, TrancheAge, Voie
from agent_he.pipeline.agent import Agent
from agent_he.referentiel.huiles import charger_referentiel
from agent_he.referentiel.rapport import rapport_markdown
from agent_he.referentiel.securite import (
    ErreurCycle,
    TableSecurite,
    controler,
    ecrire_entrees,
    entete_fichier,
    lire_entrees,
    valider,
    verifier,
)

app = typer.Typer(help="Agent personnel d'aide aux synergies d'huiles essentielles.")
securite_app = typer.Typer(help="Table de sécurité : vérification, validation, audit.")
app.add_typer(securite_app, name="securite")
corpus_app = typer.Typer(help="Corpus de recettes validées et file de validation.")
app.add_typer(corpus_app, name="corpus")


def _dossier() -> Path:
    return get_settings().data_dir


def _erreur(message: str) -> typer.Exit:
    typer.secho(message, fg=typer.colors.RED, err=True)
    return typer.Exit(code=1)


OptionPar = Annotated[str | None, typer.Option(help="Nom de la personne (défaut : réglage).")]
OptionLe = Annotated[
    str | None, typer.Option(help="Date AAAA-MM-JJ (défaut : aujourd'hui).", show_default=False)
]


def _date(le: str | None) -> date:
    return date.fromisoformat(le) if le else date.today()


def _modifier_entree(entree_id: str, operation: str, **kwargs: object) -> None:
    chemin = _dossier() / "securite.yaml"
    entrees = lire_entrees(chemin)
    index = next((i for i, e in enumerate(entrees) if e.id == entree_id), None)
    if index is None:
        raise _erreur(f"Entrée introuvable : {entree_id}")
    try:
        if operation == "verifier":
            entrees[index] = verifier(entrees[index], **kwargs)  # type: ignore[arg-type]
        else:
            entrees[index] = valider(entrees[index], **kwargs)  # type: ignore[arg-type]
    except ErreurCycle as exc:
        raise _erreur(str(exc)) from exc
    ecrire_entrees(chemin, entrees, entete=entete_fichier(chemin))
    typer.echo(f"{entree_id} : statut {entrees[index].statut}")


@securite_app.command("verifier")
def securite_verifier(
    entree_id: Annotated[str, typer.Argument(help="Identifiant, ex. SEC-0001.")],
    conforme: Annotated[
        bool, typer.Option("--conforme", help="Checklist §8 entièrement cochée.")
    ] = False,
    non_conforme: Annotated[
        str | None, typer.Option("--non-conforme", help="Point de la checklist en échec.")
    ] = None,
    par: OptionPar = None,
    le: OptionLe = None,
) -> None:
    """Enregistre la vérification d'une entrée contre le livre (règle §6, §8)."""
    if conforme == (non_conforme is not None):
        raise _erreur('Indiquer soit --conforme, soit --non-conforme "<commentaire>".')
    _modifier_entree(
        entree_id,
        "verifier",
        par=par or get_settings().utilisateur,
        le=_date(le),
        conforme=conforme,
        commentaire=non_conforme,
    )


@securite_app.command("valider")
def securite_valider(
    entree_id: Annotated[str, typer.Argument(help="Identifiant, ex. SEC-0001.")],
    par: OptionPar = None,
    le: OptionLe = None,
) -> None:
    """Met en service une entrée vérifiée conforme (empreinte contrôlée, règle §7)."""
    _modifier_entree(entree_id, "valider", par=par or get_settings().utilisateur, le=_date(le))


@securite_app.command("controler")
def securite_controler() -> None:
    """Lance les contrôles automatiques (règle §9) ; code de sortie 1 en cas de problème."""
    dossier = _dossier()
    table = TableSecurite.depuis_fichier(dossier / "securite.yaml")
    problemes = controler(table, charger_referentiel(dossier))
    for alerte in table.alertes:
        typer.secho(f"⚠️  {alerte}", fg=typer.colors.YELLOW)
    if problemes:
        for probleme in problemes:
            typer.secho(f"❌ {probleme}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    typer.echo(f"✅ {len(table.entrees)} entrée(s), aucun problème bloquant.")


@securite_app.command("rapport")
def securite_rapport(
    sortie: Annotated[
        Path | None,
        typer.Option(help="Fichier de sortie (défaut : docs/audit/securite-<date>.md)."),
    ] = None,
) -> None:
    """Produit le rapport d'audit Markdown imprimable (règle §9)."""
    dossier = _dossier()
    jour = date.today()
    table = TableSecurite.depuis_fichier(dossier / "securite.yaml")
    texte = rapport_markdown(table, charger_referentiel(dossier), jour)
    chemin = sortie or Path("docs/audit") / f"securite-{jour.isoformat()}.md"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(texte, encoding="utf-8")
    typer.echo(f"Rapport écrit : {chemin}")


def construire_magasin(reglages: Settings) -> Magasin:
    try:
        return services.construire_magasin(reglages)
    except services.ErreurConfiguration as exc:
        raise _erreur(str(exc)) from exc


def file_validation(reglages: Settings) -> FileValidation:
    return services.file_validation(reglages)


@corpus_app.command("reindex")
def corpus_reindex() -> None:
    """Reconstruit l'index du corpus à partir de data/recettes/."""
    reglages = get_settings()
    corpus = reindexer(reglages.data_dir / "recettes", construire_magasin(reglages))
    typer.echo(f"{len(corpus)} recette(s) indexée(s).")


@corpus_app.command("candidates")
def corpus_candidates(
    toutes: Annotated[bool, typer.Option(help="Inclure les candidates déjà traitées.")] = False,
) -> None:
    """Liste les recettes web en attente de relecture."""
    candidates = file_validation(get_settings()).lister(None if toutes else "en_attente")
    if not candidates:
        typer.echo("Aucune candidate.")
    for c in candidates:
        huiles = ", ".join(h.nom for h in c.recette.huiles)
        typer.echo(
            f"{c.id}  [{c.statut}]  {c.recette.nom_recette} ({c.recette.voie}) — {huiles} — "
            f"{', '.join(c.recette.sources)}"
        )


@corpus_app.command("valider")
def corpus_valider(
    candidate_id: Annotated[str, typer.Argument(help="Identifiant de la candidate.")],
    besoin: Annotated[
        list[Besoin] | None, typer.Option(help="Besoins couverts (défaut : ceux détectés).")
    ] = None,
    identifiant: Annotated[str | None, typer.Option(help="Identifiant dans le corpus.")] = None,
    par: OptionPar = None,
) -> None:
    """Valide une candidate après relecture : export dans data/recettes/ puis réindexation."""
    reglages = get_settings()
    try:
        recette = file_validation(reglages).valider(
            candidate_id,
            par=par or reglages.utilisateur,
            dossier_recettes=reglages.data_dir / "recettes",
            besoins=besoin or None,
            identifiant=identifiant,
        )
    except ErreurValidation as exc:
        raise _erreur(str(exc)) from exc
    typer.echo(f"Recette ajoutée au corpus : {recette.id}")
    corpus_reindex()


@corpus_app.command("rejeter")
def corpus_rejeter(
    candidate_id: Annotated[str, typer.Argument(help="Identifiant de la candidate.")],
    motif: Annotated[str, typer.Option(help="Motif du rejet.")],
) -> None:
    """Rejette une candidate."""
    try:
        file_validation(get_settings()).rejeter(candidate_id, motif)
    except ErreurValidation as exc:
        raise _erreur(str(exc)) from exc
    typer.echo(f"{candidate_id} rejetée.")


def construire_agent(reglages: Settings) -> Agent:
    """Agent branché sur les vrais services (Mistral, Tavily)."""
    try:
        return services.construire_agent(reglages)
    except services.ErreurConfiguration as exc:
        raise _erreur(str(exc)) from exc


@app.command("ask")
def ask(
    besoin: Annotated[str, typer.Argument(help="Besoin, ex. « mélange pour dormir ».")],
    voie: Annotated[list[Voie], typer.Option(help="Voie(s) d'utilisation.")],
    age: Annotated[TrancheAge, typer.Option(help="Tranche d'âge de la personne concernée.")],
    grossesse: Annotated[bool, typer.Option(help="Grossesse ou allaitement.")] = False,
    epilepsie: Annotated[bool, typer.Option(help="Épilepsie.")] = False,
    asthme: Annotated[bool, typer.Option(help="Asthme.")] = False,
    traitement: Annotated[bool, typer.Option(help="Traitement médicamenteux en cours.")] = False,
    allergies: Annotated[bool, typer.Option(help="Allergies connues / peau sensible.")] = False,
    hormonal: Annotated[bool, typer.Option(help="Pathologie hormonodépendante.")] = False,
    texte: Annotated[str, typer.Option(help="Précisions libres.")] = "",
    confirme: Annotated[
        bool, typer.Option(help="Confirme le questionnaire malgré un risque détecté dans le texte.")
    ] = False,
) -> None:
    """Cherche une recette sûre pour un besoin (questionnaire de sécurité obligatoire)."""
    from agent_he.safety.keywords import charger_filet

    reglages = get_settings()
    questionnaire = Questionnaire(
        age=age,
        grossesse_allaitement=grossesse,
        epilepsie=epilepsie,
        asthme=asthme,
        traitement=traitement,
        allergies=allergies,
        pathologie_hormonale=hormonal,
    )
    demande = Demande(besoin=besoin, voies=voie, texte_libre=texte, questionnaire=questionnaire)
    risques = charger_filet(reglages.data_dir).risques_non_coches(
        f"{besoin} {texte}", questionnaire
    )
    if risques and not confirme:
        raise _erreur(
            f"Risque détecté dans ta demande mais non coché : {', '.join(risques)}. "
            "Complète le questionnaire, ou relance avec --confirme si c'est sans objet."
        )
    reponse = construire_agent(reglages).repondre(demande)
    typer.echo(fiche_markdown(reponse.fiche, reponse.sources))


if __name__ == "__main__":  # pragma: no cover
    app()
