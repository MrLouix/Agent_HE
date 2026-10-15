"""Interface Streamlit locale (spécification §10).

Les services (agent, historique, favoris, file de validation) sont placés dans
`st.session_state["services"]` : construits depuis les réglages au premier affichage,
ou injectés par les tests (`AppTest`) avec un agent simulé.
"""

from dataclasses import dataclass

import streamlit as st

from agent_he.config import get_settings
from agent_he.export import BANDEAU, fiche_markdown
from agent_he.kb.validation import FileValidation
from agent_he.models import Demande, Questionnaire, TrancheAge, Voie
from agent_he.pipeline.agent import Agent, Reponse
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
    erreur: str | None = None


def services_par_defaut() -> Services:
    from agent_he.services import ErreurConfiguration, construire_agent
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
        erreur=erreur,
    )


def services() -> Services:
    if "services" not in st.session_state:
        st.session_state["services"] = services_par_defaut()
    resultat: Services = st.session_state["services"]
    return resultat


# --- Barre latérale ---------------------------------------------------------------------


def barre_laterale() -> tuple[str, list[Voie], TrancheAge | None, dict[str, bool]]:
    with st.sidebar:
        st.header("Ta demande")
        besoin = st.text_input("Besoin", key="besoin", placeholder="ex. mieux dormir")
        voies = st.multiselect(
            "Voie(s)", list(Voie), format_func=lambda v: LIBELLES_VOIES[v], key="voies"
        )
        st.header("Questionnaire de sécurité")
        st.caption("Obligatoire. Il porte sur la personne qui utilisera le mélange.")
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
        st.error(f"⛔ Aucun dosage proposé. {fiche.motif}")
        if fiche.he_a_eviter:
            st.markdown("**HE à éviter pour ce profil :** " + ", ".join(fiche.he_a_eviter))
        st.info(RENVOI_PROFESSIONNEL)
        return
    if fiche.mode == "aucune":
        st.warning(fiche.motif or "Aucune recette sûre trouvée.")
        return
    for avertissement in fiche.avertissements:
        st.warning(avertissement)
    st.markdown(fiche_markdown(fiche))


def afficher_sources(reponse: Reponse) -> None:
    if not reponse.sources:
        st.caption("Aucune source pour cette réponse.")
    for source in reponse.sources:
        st.markdown(f"{BADGES[source.confiance]} — [{source.titre}]({source.url})")


def onglet_historique(svc: Services) -> None:
    entrees = svc.historique.lister()
    if not entrees:
        st.caption("Aucune recherche pour l'instant.")
    for e in entrees:
        titre = e.fiche.recette.nom_recette if e.fiche.recette else e.fiche.mode
        besoin = e.demande.besoin if e.demande else ""
        with st.expander(f"{e.horodatage:%d/%m/%Y %H:%M} — {besoin} — {titre}"):
            st.markdown(fiche_markdown(e.fiche, e.sources))


def onglet_favoris(svc: Services) -> None:
    favoris = svc.favoris.lister()
    if not favoris:
        st.caption("Aucun favori.")
    for f in favoris:
        with st.expander(f"⭐ {f.nom}"):
            st.markdown(fiche_markdown(f.fiche, f.sources))
            if st.button("Retirer des favoris", key=f"retirer-{f.id}"):
                svc.favoris.supprimer(f.id)
                st.rerun()


def onglet_validation(svc: Services) -> None:
    candidates = svc.file_validation.lister()
    if not candidates:
        st.caption("Aucune recette en attente de relecture.")
    for c in candidates:
        with st.expander(f"{c.id} — {c.recette.nom_recette} ({c.recette.voie})"):
            for h in c.recette.huiles:
                st.markdown(
                    f"- {h.nom} (*{h.nom_latin}*) : {h.quantite.valeur:g} {h.quantite.unite}"
                )
            st.caption("Sources : " + ", ".join(c.recette.sources))
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
    """Exclusions personnelles (alimentées par le journal d'usage)."""
    del svc
    return {}


def main() -> None:
    st.set_page_config(page_title="Agent HE", page_icon="🌿", layout="wide")
    st.warning(BANDEAU, icon="⚠️")
    st.title("🌿 Agent huiles essentielles")
    svc = services()
    if svc.erreur:
        st.error(svc.erreur)

    besoin, voies, age, reponses = barre_laterale()
    precisions = st.chat_input("Précise ta demande (facultatif)")
    if precisions:
        st.session_state["texte_libre"] = precisions
    texte_libre: str = st.session_state.get("texte_libre", "")
    if texte_libre:
        st.caption(f"Précisions : {texte_libre}")

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
            f"{', '.join(risques)}. Complète le questionnaire ou confirme qu'il est sans objet."
        )
        confirme = st.checkbox("Je confirme que le questionnaire est exact", key="confirmation")

    if st.sidebar.button("Rechercher", type="primary", key="rechercher"):
        if manquants:
            st.error(
                "Recherche bloquée : remplis d'abord le questionnaire et la demande "
                f"({', '.join(manquants)})."
            )
        elif not confirme:
            st.error("Recherche bloquée : confirme le questionnaire.")
        elif svc.agent is None:
            st.error("Recherche impossible : l'agent n'est pas configuré.")
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
    noms = [
        "Fiche",
        "Sources",
        "Produits",
        "Journal",
        "Historique",
        "Favoris",
        "File de validation",
    ]
    onglets = dict(zip(noms, st.tabs(noms), strict=True))
    with onglets["Fiche"]:
        if reponse is None:
            st.caption("Remplis la barre latérale puis lance la recherche.")
        else:
            afficher_fiche(reponse)
            avec_recette = reponse.fiche.recette is not None
            if avec_recette and st.button("⭐ Ajouter aux favoris", key="favori"):
                svc.favoris.ajouter(reponse.fiche, reponse.sources, reponse.recette_ref)
                st.success("Ajoutée aux favoris.")
            st.download_button(
                "Exporter la fiche (Markdown)",
                fiche_markdown(reponse.fiche, reponse.sources),
                file_name="fiche-he.md",
                mime="text/markdown",
            )
    with onglets["Sources"]:
        if reponse is not None:
            afficher_sources(reponse)
    with onglets["Produits"]:
        st.caption("Comparatif produits : disponible après configuration des boutiques.")
    with onglets["Journal"]:
        st.caption("Journal d'usage : bientôt disponible.")
    with onglets["Historique"]:
        onglet_historique(svc)
    with onglets["Favoris"]:
        onglet_favoris(svc)
    with onglets["File de validation"]:
        onglet_validation(svc)
