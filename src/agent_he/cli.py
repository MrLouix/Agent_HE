"""Interface en ligne de commande `agent-he`."""

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from agent_he.config import get_settings
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


if __name__ == "__main__":  # pragma: no cover
    app()
