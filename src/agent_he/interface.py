"""Interface Streamlit locale (spécification §10).

Les services (agent, historique, favoris, file de validation) sont placés dans
`st.session_state["services"]` : construits depuis les réglages au premier affichage,
ou injectés par les tests (`AppTest`) avec un agent simulé.
"""

from dataclasses import dataclass

import streamlit as st

from agent_he.config import get_settings
from agent_he.export import BANDEAU, fiche_markdown
from agent_he.journal.repository import ErreurJournal, Journal
from agent_he.journal.saisie import parser_melange, utilisations_sans_retour
from agent_he.journal.stats import preferences_olfactives, rappel, stats_par_he, stats_recette
from agent_he.journal.tolerance import he_suspectes, propositions_exclusion
from agent_he.kb.validation import FileValidation
from agent_he.models import (
    Demande,
    EntreeUsage,
    ExclusionPerso,
    Questionnaire,
    Tolerance,
    TrancheAge,
    Voie,
)
from agent_he.pipeline.agent import Agent, Reponse
from agent_he.products.compare import Comparateur
from agent_he.referentiel.huiles import Referentiel, charger_referentiel
from agent_he.safety.keywords import FiletMotsCles, charger_filet
from agent_he.safety.questionnaire import RENVOI_PROFESSIONNEL
from agent_he.search.reliability import BADGES
from agent_he.storage.favorites import Favoris, Historique

LIBELLES_AGES = {
    TrancheAge.MOINS_3: "moins de 3 ans",
    TrancheAge.DE_3_A_6: "3 à 6 ans",
    TrancheAge.DE_6_A_12: "6 à 12 ans",
    TrancheAge.DE_12_A_18: "12 à 18 ans",
    TrancheAge.ADULTE: "adulte",
    TrancheAge.PLUS_65: "plus de 65 ans",
}
LIBELLES_VOIES = {
    Voie.DIFFUSION: "Diffusion",
    Voie.CUTANEE: "Application cutanée",
    Voie.BAIN: "Bain",
    Voie.MASSAGE: "Massage",
    Voie.INHALATION: "Inhalation",
}
_QUESTIONS = {
    "grossesse_allaitement": "Grossesse ou allaitement",
    "epilepsie": "Épilepsie",
    "asthme": "Asthme",
    "traitement": "Traitement médicamenteux en cours",
    "allergies": "Allergies connues / peau sensible",
    "pathologie_hormonale": "Pathologie hormonodépendante",
}


@dataclass
class Services:
    agent: Agent | None
    historique: Historique
    favoris: Favoris
    file_validation: FileValidation
    filet: FiletMotsCles
    journal: Journal
    referentiel: Referentiel
    comparateur: Comparateur | None = None
    erreur: str | None = None
    seuil_reactions_fortes: int = 1
    seuil_reactions_legeres: int = 2


def services_par_defaut() -> Services:
    from agent_he.services import ErreurConfiguration, construire_agent, construire_comparateur
    from agent_he.storage.db import connecter

    reglages = get_settings()
    connexion = connecter(reglages.db_path)
    agent: Agent | None = None
    erreur: str | None = None
    try:
        agent = construire_agent(reglages)
    except ErreurConfiguration as exc:
        erreur = str(exc)
    return Services(
        agent=agent,
        historique=Historique(connexion),
        favoris=Favoris(connexion),
        file_validation=FileValidation(connexion),
        filet=charger_filet(reglages.data_dir),
        journal=Journal(connexion),
        referentiel=charger_referentiel(reglages.data_dir),
        comparateur=construire_comparateur(reglages),
        erreur=erreur,
        seuil_reactions_fortes=reglages.seuil_reactions_fortes,
        seuil_reactions_legeres=reglages.seuil_reactions_legeres,
    )


def services() -> Services:
    if "services" not in st.session_state:
        st.session_state["services"] = services_par_defaut()
    resultat: Services = st.session_state["services"]
    return resultat


# --- Barre latérale ---------------------------------------------------------------------


def barre_laterale() -> tuple[str, list[Voie], TrancheAge | None, dict[str, bool]]:
    with st.sidebar:
        st.header("Ta demande", icon=":material/edit_note:")
        besoin = st.text_input("Besoin", key="besoin", placeholder="ex. mieux dormir")
        voies = st.pills(
            "Voie(s)",
            list(Voie),
            selection_mode="multi",
            format_func=lambda v: LIBELLES_VOIES[v],
            key="voies",
        )
        st.header("Questionnaire de sécurité", icon=":material/health_and_safety:")
        st.caption("Obligatoire. Il porte sur la personne qui utilisera le mélange.")
        with st.container(border=True):
            age = st.selectbox(
                "Âge de la personne concernée",
                list(TrancheAge),
                index=None,
                format_func=lambda a: LIBELLES_AGES[a],
                placeholder="Choisir…",
                key="age",
            )
            reponses = {cle: st.checkbox(libelle, key=cle) for cle, libelle in _QUESTIONS.items()}
    return besoin, voies, age, reponses


# --- Affichage d'une réponse ------------------------------------------------------------


def afficher_fiche(reponse: Reponse) -> None:
    fiche = reponse.fiche
    if fiche.mode == "refus":
        st.error(fiche.motif, title="Aucun dosage proposé", icon=":material/block:")
        if fiche.he_a_eviter:
            st.markdown(
                "**HE à éviter pour ce profil :** "
                + " ".join(f":red-badge[{he}]" for he in fiche.he_a_eviter)
            )
        st.info(RENVOI_PROFESSIONNEL, icon=":material/stethoscope:")
        return
    if fiche.mode == "aucune":
        st.warning(fiche.motif or "Aucune recette sûre trouvée.", icon=":material/search_off:")
        return
    for avertissement in fiche.avertissements:
        st.warning(avertissement)
    st.markdown(fiche_markdown(fiche))


def afficher_sources(reponse: Reponse) -> None:
    if not reponse.sources:
        st.caption("Aucune source pour cette réponse.")
    for source in reponse.sources:
        with st.container(border=True):
            st.markdown(f"[{source.titre}]({source.url})  \n{BADGES[source.confiance]}")


def onglet_produits(svc: Services, reponse: Reponse | None) -> None:
    if svc.comparateur is None or not svc.comparateur.boutiques:
        st.caption(
            "Aucune boutique active : vérifie leurs CGU et robots.txt, puis complète "
            "data/boutiques.yaml (cgu_verifiees, url_recherche, motif_lien_produit)."
        )
        return
    if reponse is None or reponse.fiche.recette is None:
        st.caption("Le comparatif porte sur les HE de la fiche affichée.")
        return
    if not st.button("Comparer les produits", key="comparer", icon=":material/compare_arrows:"):
        return
    for dose in reponse.fiche.recette.huiles:
        with st.container(border=True):
            st.markdown(f"**{dose.nom}** (*{dose.nom_latin}*)")
            produits, erreurs = svc.comparateur.comparer(dose.he_id)
            for p in produits:
                st.markdown(f"- {p.carte()}")
            if not produits:
                st.caption("Aucun produit trouvé.")
            for erreur in erreurs:
                st.caption(f":material/warning: {erreur}")


def onglet_historique(svc: Services) -> None:
    entrees = svc.historique.lister()
    if not entrees:
        st.caption("Aucune recherche pour l'instant.")
    for e in entrees:
        titre = e.fiche.recette.nom_recette if e.fiche.recette else e.fiche.mode
        besoin = e.demande.besoin if e.demande else ""
        with st.expander(
            f"{e.horodatage:%d/%m/%Y %H:%M} — {besoin} — {titre}", icon=":material/history:"
        ):
            st.markdown(fiche_markdown(e.fiche, e.sources))


def onglet_favoris(svc: Services) -> None:
    favoris = svc.favoris.lister()
    if not favoris:
        st.caption("Aucun favori.")
    for f in favoris:
        with st.expander(f.nom, icon=":material/star:"):
            st.markdown(fiche_markdown(f.fiche, f.sources))
            if f.fiche.recette is not None:
                st.markdown(":material/edit_note: **J'ai utilisé cette recette**")
                formulaire_usage(
                    svc,
                    f"favori-{f.id}",
                    f.recette_ref,
                    [h.he_id for h in f.fiche.recette.huiles],
                    f.fiche.recette.voie,
                )
            if st.button("Retirer des favoris", key=f"retirer-{f.id}", icon=":material/delete:"):
                svc.favoris.supprimer(f.id)
                st.rerun()


def onglet_validation(svc: Services) -> None:
    candidates = svc.file_validation.lister()
    if not candidates:
        st.caption("Aucune recette en attente de relecture.")
    for c in candidates:
        with st.expander(
            f"{c.id} — {c.recette.nom_recette} ({c.recette.voie})", icon=":material/rule:"
        ):
            for h in c.recette.huiles:
                st.markdown(
                    f"- {h.nom} (*{h.nom_latin}*) : {h.quantite.valeur:g} {h.quantite.unite}"
                )
            st.caption("Sources : " + ", ".join(c.recette.sources))
            retours = stats_recette(svc.journal.lister(), c.recette.nom_recette)
            if retours is not None:
                # Aide à la décision seulement : une bonne note ne valide jamais une recette.
                st.info(
                    f"Ton journal : {rappel(retours)} ; {len(retours.reactions)} réaction(s).",
                    icon=":material/menu_book:",
                )
            st.caption(
                f"Valider ou rejeter : `agent-he corpus valider {c.id}` / "
                f"`agent-he corpus rejeter {c.id} --motif …`"
            )


# --- Page -------------------------------------------------------------------------------


def lancer_recherche(svc: Services, demande: Demande) -> None:
    assert svc.agent is not None
    with st.status("Recherche en cours…", expanded=False) as statut:
        st.write("Contrôle de sécurité, corpus validé, puis sources web de confiance…")
        reponse = svc.agent.repondre(demande, exclusions_perso=exclusions(svc))
        statut.update(label="Recherche terminée", state="complete")
    st.session_state["reponse"] = reponse
    svc.historique.ajouter(demande, reponse.fiche, reponse.sources, reponse.recette_ref)


def exclusions(svc: Services) -> dict[str, str]:
    """Exclusions personnelles confirmées (journal d'usage)."""
    return svc.journal.exclusions()


# --- Journal d'usage (spécification §11) -------------------------------------------------

_TOLERANCES = {
    Tolerance.AUCUNE: "Aucune réaction",
    Tolerance.LEGERE: "Réaction légère",
    Tolerance.FORTE: "Réaction forte",
}


def formulaire_usage(
    svc: Services,
    cle: str,
    recette_ref: str | None,
    huiles: list[str],
    voie: Voie | None,
) -> None:
    """Saisie rapide : seuls les champs obligatoires sont visibles, le reste est replié."""
    with st.form(key=f"usage-{cle}", clear_on_submit=True):
        melange = ""
        if recette_ref is None:
            melange = st.text_area(
                "Mélange (nom:quantité:unité, séparés par « ; »)",
                placeholder="lavande fine:3:gouttes; orange douce:2:gouttes",
                key=f"melange-{cle}",
            )
        voie_choisie = st.selectbox(
            "Voie",
            list(Voie),
            index=list(Voie).index(voie) if voie else 0,
            format_func=lambda v: LIBELLES_VOIES[v],
            key=f"voie-{cle}",
        )
        efficacite = st.select_slider(
            "Efficacité", options=["sans objet", 1, 2, 3, 4, 5], value=3, key=f"eff-{cle}"
        )
        tolerance = st.segmented_control(
            "Tolérance",
            list(Tolerance),
            default=Tolerance.AUCUNE,
            required=True,
            format_func=lambda t: _TOLERANCES[t],
            key=f"tol-{cle}",
        )
        reaction = st.text_input("Description de la réaction (si réaction)", key=f"reac-{cle}")
        with st.expander("Plus de détails (facultatif)"):
            odeur = st.select_slider(
                "Odeur", options=["—", 1, 2, 3, 4, 5], value="—", key=f"odeur-{cle}"
            )
            personne = st.text_input("Personne concernée", value="moi", key=f"pers-{cle}")
            contexte = st.text_input("Contexte (moment, durée…)", key=f"ctx-{cle}")
            notes = st.text_area("Notes", key=f"notes-{cle}")
        if st.form_submit_button("Enregistrer le retour", icon=":material/save:"):
            try:
                if voie_choisie is None or tolerance is None:
                    raise ErreurJournal("voie et tolérance obligatoires")
                doses = parser_melange(melange, svc.referentiel) if recette_ref is None else None
                entree = EntreeUsage(
                    recette_ref=recette_ref,
                    melange_libre=doses,
                    voie=voie_choisie,
                    personne=personne or "moi",
                    efficacite=None if efficacite == "sans objet" else int(str(efficacite)),
                    tolerance=tolerance,
                    description_reaction=reaction or None,
                    odeur=None if odeur == "—" else int(str(odeur)),
                    contexte=contexte or None,
                    notes=notes or None,
                )
                svc.journal.ajouter(entree, [] if doses else huiles)
            except (ErreurJournal, ValueError) as exc:
                st.error(f"Retour non enregistré : {exc}")
            else:
                st.success("Retour enregistré dans ton journal.")


def nom_he(svc: Services, he_id: str) -> str:
    huile = svc.referentiel.get(he_id)
    return huile.nom if huile else he_id


def onglet_journal(svc: Services) -> None:
    entrees = svc.journal.lister()
    rappels = utilisations_sans_retour(svc.historique, svc.journal)
    for ref in rappels:
        st.info(
            f"Tu as consulté « {ref} » récemment : ajoute ton retour depuis la fiche.",
            icon=":material/notifications:",
        )

    st.subheader("Réactions et exclusions", icon=":material/healing:")
    propositions = propositions_exclusion(
        entrees,
        set(svc.journal.exclusions()),
        svc.seuil_reactions_fortes,
        svc.seuil_reactions_legeres,
    )
    for p in propositions:
        st.warning(f"Proposition : exclure {nom_he(svc, p.he_id)} — {p.motif}.")
        if st.button(
            f"Confirmer l'exclusion de {nom_he(svc, p.he_id)}",
            key=f"exclure-{p.he_id}",
            icon=":material/block:",
        ):
            svc.journal.confirmer_exclusion(
                ExclusionPerso(he_id=p.he_id, motif=p.motif, entrees_liees=list(p.entrees))
            )
            st.rerun()
    suspectes = he_suspectes(entrees)
    if suspectes:
        st.markdown(
            "**HE suspectes** (présentes dans les mélanges avec réaction, absentes des mélanges "
            "bien tolérés) : "
            + " ".join(
                f":orange-badge[{nom_he(svc, s.he_id)} ({s.nb_reactions})]" for s in suspectes
            )
        )
    exclues = svc.journal.liste_exclusions()
    if not (propositions or suspectes or exclues):
        st.caption("Aucune réaction signalée.")
    for e in exclues:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(
                f":material/block: **{nom_he(svc, e.he_id)}** — {e.motif} "
                f"(depuis le {e.date_ajout:%d/%m/%Y})"
            )
            if st.button(
                "Retirer", key=f"retirer-excl-{e.he_id}", icon=":material/undo:", type="tertiary"
            ):
                svc.journal.retirer_exclusion(e.he_id)
                st.rerun()

    st.subheader("Préférences olfactives", icon=":material/air:")
    prefs = preferences_olfactives(entrees)
    appreciees = " ".join(f":green-badge[{nom_he(svc, h)}]" for h in prefs.appreciees)
    detestees = " ".join(f":red-badge[{nom_he(svc, h)}]" for h in prefs.detestees)
    st.markdown(f"Appréciées : {appreciees or '—'}  \nDétestées : {detestees or '—'}")

    st.subheader("Historique", icon=":material/history:")
    stats = stats_par_he(entrees)
    if not entrees:
        st.caption("Aucun retour enregistré pour l'instant.")
    else:
        filtre = st.selectbox(
            "Filtrer sur une HE",
            sorted(stats),
            index=None,
            format_func=lambda h: nom_he(svc, h),
            placeholder="Toutes les HE",
            key="filtre-journal",
        )
        st.dataframe(
            [
                {
                    "Date": entree.horodatage,
                    "Recette": entree.recette_ref or "mélange libre",
                    "HE": ", ".join(nom_he(svc, h) for h in huiles),
                    "Efficacité": entree.efficacite,
                    "Tolérance": _TOLERANCES[entree.tolerance],
                }
                for entree, huiles in svc.journal.lister(he_id=filtre)
            ],
            hide_index=True,
            column_config={
                "Date": st.column_config.DatetimeColumn(format="DD/MM/YYYY"),
                "Efficacité": st.column_config.NumberColumn(format="%d/5"),
            },
            alt="Historique des retours d'usage",
        )
        st.dataframe(
            [
                {
                    "HE": nom_he(svc, he_id),
                    "Usages": s.nb_usages,
                    "Efficacité moy.": s.efficacite_moy,
                    "Odeur moy.": s.odeur_moy,
                    "Réactions légères": s.nb_reactions_legeres,
                    "Réactions fortes": s.nb_reactions_fortes,
                }
                for he_id, s in stats.items()
            ],
            hide_index=True,
            alt="Statistiques par huile essentielle",
        )

    st.subheader("Ajouter un mélange libre", icon=":material/add_circle:")
    formulaire_usage(svc, "libre", None, [], None)


def main() -> None:
    st.title("Agent huiles essentielles", icon=":material/spa:")
    st.warning(BANDEAU.removeprefix("⚠️").strip(), icon=":material/health_and_safety:")
    svc = services()
    if svc.erreur:
        st.error(svc.erreur, title="Configuration incomplète", icon=":material/key_off:")

    besoin, voies, age, reponses = barre_laterale()
    precisions = st.chat_input("Précise ta demande (facultatif)")
    if precisions:
        st.session_state["texte_libre"] = precisions
    texte_libre: str = st.session_state.get("texte_libre", "")
    if texte_libre:
        st.caption(f":material/chat: Précisions : {texte_libre}")

    manquants = [
        libelle
        for libelle, ok in (("besoin", besoin.strip()), ("voie", voies), ("âge", age is not None))
        if not ok
    ]
    risques: list[str] = []
    if age is not None:
        questionnaire = Questionnaire(age=age, **reponses)
        risques = svc.filet.risques_non_coches(f"{besoin} {texte_libre}", questionnaire)
    confirme = True
    if risques:
        st.warning(
            "Ta demande mentionne un risque non coché dans le questionnaire : "
            f"{', '.join(risques)}. Complète le questionnaire ou confirme qu'il est sans objet.",
            icon=":material/priority_high:",
        )
        confirme = st.checkbox("Je confirme que le questionnaire est exact", key="confirmation")

    if st.sidebar.button(
        "Rechercher", type="primary", key="rechercher", icon=":material/search:", width="stretch"
    ):
        if manquants:
            st.error(
                "Recherche bloquée : remplis d'abord le questionnaire et la demande "
                f"({', '.join(manquants)}).",
                icon=":material/lock:",
            )
        elif not confirme:
            st.error("Recherche bloquée : confirme le questionnaire.", icon=":material/lock:")
        elif svc.agent is None:
            st.error("Recherche impossible : l'agent n'est pas configuré.", icon=":material/error:")
        else:
            assert age is not None
            demande = Demande(
                besoin=besoin,
                voies=voies,
                texte_libre=texte_libre,
                questionnaire=Questionnaire(age=age, **reponses),
            )
            lancer_recherche(svc, demande)

    reponse: Reponse | None = st.session_state.get("reponse")
    icones = {
        "Fiche": "description",
        "Sources": "link",
        "Produits": "shopping_bag",
        "Journal": "menu_book",
        "Historique": "history",
        "Favoris": "star",
        "File de validation": "rule",
    }
    onglets = dict(
        zip(icones, st.tabs([f":material/{i}: {n}" for n, i in icones.items()]), strict=True)
    )
    with onglets["Fiche"]:
        if reponse is None:
            st.caption(":material/arrow_back: Remplis la barre latérale puis lance la recherche.")
        else:
            afficher_fiche(reponse)
            recette = reponse.fiche.recette
            with st.container(horizontal=True):
                if recette is not None and st.button(
                    "Ajouter aux favoris", key="favori", icon=":material/star:"
                ):
                    svc.favoris.ajouter(reponse.fiche, reponse.sources, reponse.recette_ref)
                    st.toast("Ajoutée aux favoris.", icon=":material/star:")
                st.download_button(
                    "Exporter la fiche (Markdown)",
                    fiche_markdown(reponse.fiche, reponse.sources),
                    file_name="fiche-he.md",
                    mime="text/markdown",
                    icon=":material/download:",
                )
            if recette is not None:
                with st.expander("J'ai utilisé cette recette", icon=":material/edit_note:"):
                    formulaire_usage(
                        svc,
                        "fiche",
                        reponse.recette_ref,
                        [h.he_id for h in recette.huiles],
                        recette.voie,
                    )
    with onglets["Sources"]:
        if reponse is None:
            st.caption("Les sources de la fiche s'afficheront ici.")
        else:
            afficher_sources(reponse)
    with onglets["Produits"]:
        onglet_produits(svc, reponse)
    with onglets["Journal"]:
        onglet_journal(svc)
    with onglets["Historique"]:
        onglet_historique(svc)
    with onglets["Favoris"]:
        onglet_favoris(svc)
    with onglets["File de validation"]:
        onglet_validation(svc)
