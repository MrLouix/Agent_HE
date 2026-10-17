"""Pages d'administration Streamlit : boutiques (CGU) et table de sécurité.

Chaque page affiche tout le contenu du fichier correspondant ; seuls les champs prévus
pour la saisie sont modifiables, les autres (identifiants, champs de suivi, empreintes)
sont en lecture seule et n'évoluent que par les actions dédiées (vérifier, valider,
retirer). Le dossier de données est `st.session_state["dossier_donnees"]` s'il est
défini (tests), sinon celui des réglages.
"""

from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import streamlit as st

from agent_he.admin import (
    ErreurAdmin,
    enregistrer_entree,
    lire_boutiques,
    lire_securite,
    modifier_boutique,
    remplacer_entree,
    retirer,
)
from agent_he.config import get_settings
from agent_he.interface import LIBELLES_AGES, LIBELLES_VOIES
from agent_he.models import Drapeau, TrancheAge, Voie
from agent_he.products.boutiques import Boutique
from agent_he.referentiel.huiles import Referentiel, charger_referentiel
from agent_he.referentiel.securite import (
    TOUTES_HE,
    EntreeSecurite,
    ErreurCycle,
    ProfilRisque,
    Statut,
    TypeEntree,
    controler,
    empreinte,
    etat_effectif,
    valider,
    verifier,
)

URL_REGLE = "https://github.com/MrLouix/Agent_HE/blob/main/docs/regle-table-securite.md"
OUVRAGE_PRIMAIRE = "Tisserand & Young, Essential Oil Safety, 2e éd., 2014"
RECHERCHE_TEST = "lavande"
NOUVELLE = "__nouvelle__"

LIBELLES_STATUTS = {
    Statut.BROUILLON: ":gray-badge[:material/edit: brouillon]",
    Statut.VERIFIE: ":blue-badge[:material/fact_check: vérifiée]",
    Statut.VALIDE: ":green-badge[:material/verified: validée]",
    Statut.RETIRE: ":red-badge[:material/block: retirée]",
}
NOMS_STATUTS = {
    Statut.BROUILLON: "Brouillons",
    Statut.VERIFIE: "Vérifiées",
    Statut.VALIDE: "Validées",
    Statut.RETIRE: "Retirées",
}
LIBELLES_TYPES = {
    TypeEntree.PLAFOND: "Plafond (une HE)",
    TypeEntree.PLAFOND_TOTAL: "Plafond total (règle générale)",
    TypeEntree.DRAPEAU: "Drapeau de risque",
    TypeEntree.INTERDIT_PROFIL: "Contre-indication (profil)",
}
LIBELLES_PROFILS: dict[Any, str] = {
    ProfilRisque.GROSSESSE_ALLAITEMENT: "Grossesse ou allaitement",
    ProfilRisque.EPILEPSIE: "Épilepsie",
    ProfilRisque.ASTHME: "Asthme",
    ProfilRisque.TRAITEMENT: "Traitement médicamenteux",
    ProfilRisque.PATHOLOGIE_HORMONALE: "Pathologie hormonodépendante",
    **{age: f"Âge : {libelle}" for age, libelle in LIBELLES_AGES.items()},
}


def dossier() -> Path:
    chemin: Path = st.session_state.get("dossier_donnees") or get_settings().data_dir
    return chemin


def _apres_ecriture(message: str) -> None:
    """Message affiché au prochain passage ; l'agent est reconstruit avec les nouveaux fichiers."""
    st.session_state["admin_message"] = message
    st.session_state.pop("services", None)
    st.rerun()


def _afficher_message() -> None:
    message = st.session_state.pop("admin_message", None)
    if message:
        st.toast(message, icon=":material/check_circle:")


def _lien(url: object | None, texte: str | None = None) -> str:
    if not url:
        return "—"
    return f"[{texte or url}]({url})"


def _ou_tiret(valeur: object) -> str:
    return "—" if valeur is None or valeur == "" else str(valeur)


# --- Boutiques -----------------------------------------------------------------------


def _base(boutique: Boutique) -> str:
    return str(boutique.url).rstrip("/")


def _url_test(boutique: Boutique) -> str | None:
    if not boutique.url_recherche or "{q}" not in boutique.url_recherche:
        return None
    return boutique.url_recherche.replace("{q}", quote_plus(RECHERCHE_TEST))


def _vue_ensemble_boutiques(boutiques: list[Boutique]) -> None:
    st.dataframe(
        [
            {
                "Boutique": b.nom,
                "Site": str(b.url),
                "CGU": str(b.url_cgu) if b.url_cgu else None,
                "robots.txt": f"{_base(b)}/robots.txt",
                "CGU vérifiées": b.cgu_verifiees,
                "Vérifiées le": b.cgu_verifiees_le,
                "Recherche configurée": bool(b.url_recherche and b.motif_lien_produit),
                "Active": b.active,
            }
            for b in boutiques
        ],
        hide_index=True,
        column_config={
            "Site": st.column_config.LinkColumn("Site"),
            "CGU": st.column_config.LinkColumn("CGU", display_text="Lire les CGU"),
            "robots.txt": st.column_config.LinkColumn("robots.txt", display_text="robots.txt"),
            "Vérifiées le": st.column_config.DateColumn("Vérifiées le", format="DD/MM/YYYY"),
        },
        alt="Récapitulatif des boutiques",
    )


def _fiche_boutique(boutique: Boutique) -> None:
    with st.container(horizontal=True):
        st.link_button("Ouvrir le site", str(boutique.url), icon=":material/storefront:")
        if boutique.url_cgu:
            st.link_button("Lire les CGU", str(boutique.url_cgu), icon=":material/gavel:")
        st.link_button("robots.txt", f"{_base(boutique)}/robots.txt", icon=":material/smart_toy:")
        url_test = _url_test(boutique)
        if url_test:
            st.link_button(
                f"Tester la recherche « {RECHERCHE_TEST} »", url_test, icon=":material/search:"
            )

    colonne_lecture, colonne_saisie = st.columns([2, 3], gap="large")
    with colonne_lecture:
        st.markdown("**:material/lock: Lecture seule**")
        st.table(
            {
                "Identifiant": f"`{boutique.id}`",
                "Nom": boutique.nom,
                "Site": _lien(boutique.url),
                "Accès": boutique.acces,
                "Extraction": boutique.extraction,
                "État": ":green-badge[active]" if boutique.active else ":gray-badge[inactive]",
            },
            border="horizontal",
        )
        if not boutique.active:
            manque = [
                libelle
                for libelle, ok in (
                    ("CGU vérifiées", boutique.cgu_verifiees),
                    ("URL de recherche", boutique.url_recherche),
                    ("motif des liens produit", boutique.motif_lien_produit),
                )
                if not ok
            ]
            st.caption(f":material/info: Pour l'activer, renseigner : {', '.join(manque)}.")

    with colonne_saisie, st.form(f"boutique_{boutique.id}", border=True):
        st.markdown("**:material/edit: À renseigner**")
        url_cgu = st.text_input(
            "Page des CGU",
            value=str(boutique.url_cgu) if boutique.url_cgu else "",
            placeholder="https://…/cgv",
        )
        with st.container(horizontal=True, vertical_alignment="bottom"):
            verifiees = st.toggle("CGU lues et compatibles", value=boutique.cgu_verifiees)
            verifiees_le = st.date_input(
                "Vérifiées le",
                value=boutique.cgu_verifiees_le,
                format="DD/MM/YYYY",
                help="Laissé vide, la date du jour est retenue quand les CGU sont vérifiées.",
            )
        delai = st.number_input(
            "Délai entre deux requêtes (s)", min_value=1.0, value=float(boutique.delai_s), step=1.0
        )
        url_recherche = st.text_input(
            "URL de recherche",
            value=boutique.url_recherche or "",
            placeholder=f"{_base(boutique)}/recherche?q={{q}}",
            help="Doit contenir {q}, remplacé par les termes recherchés.",
        )
        motif = st.text_input(
            "Motif des liens produit (expression régulière)",
            value=boutique.motif_lien_produit or "",
            placeholder=r"/produit/[\w-]+",
        )
        if st.form_submit_button("Enregistrer", type="primary", icon=":material/save:"):
            changements = {
                "url_cgu": url_cgu,
                "cgu_verifiees": verifiees,
                "cgu_verifiees_le": (verifiees_le or date.today()) if verifiees else None,
                "delai_s": delai,
                "url_recherche": url_recherche,
                "motif_lien_produit": motif,
            }
            try:
                modifier_boutique(dossier(), boutique.id, changements)
            except ErreurAdmin as exc:
                st.error(str(exc), title="Enregistrement refusé", icon=":material/error:")
            else:
                _apres_ecriture(f"{boutique.nom} : enregistré.")


def page_boutiques() -> None:
    _afficher_message()
    st.caption(
        "Configuration de `data/boutiques.yaml`. Le comparatif refuse toute boutique dont "
        "les CGU ne sont pas vérifiées et respecte toujours son robots.txt."
    )
    try:
        boutiques = lire_boutiques(dossier())
    except (OSError, ValueError) as exc:
        st.error(str(exc), title="Fichier illisible", icon=":material/error:")
        return
    if not boutiques:
        st.info("Aucune boutique dans le fichier.", icon=":material/info:")
        return
    _vue_ensemble_boutiques(boutiques)
    st.subheader("Détail par boutique", icon=":material/storefront:")
    for onglet, boutique in zip(st.tabs([b.nom for b in boutiques]), boutiques, strict=True):
        with onglet:
            _fiche_boutique(boutique)


# --- Table de sécurité ---------------------------------------------------------------


def _referentiel() -> Referentiel:
    return charger_referentiel(dossier())


def _nom_he(referentiel: Referentiel, he_id: str) -> str:
    if he_id == TOUTES_HE:
        return "Toutes les HE (*)"
    huile = referentiel.get(he_id)
    return f"{huile.nom} ({he_id})" if huile else he_id


def _resume_valeur(e: EntreeSecurite) -> str:
    if e.valeur is not None:
        return f"{e.valeur:g} {e.unite or ''}".strip()
    if e.drapeau is not None:
        return str(e.drapeau)
    if e.profil is not None:
        return LIBELLES_PROFILS.get(e.profil, str(e.profil))
    return "—"


def _vue_ensemble_securite(entrees: list[EntreeSecurite], referentiel: Referentiel) -> None:
    with st.container(horizontal=True):
        st.metric("Entrées", len(entrees), border=True)
        for statut in Statut:
            st.metric(NOMS_STATUTS[statut], sum(e.statut == statut for e in entrees), border=True)
    problemes = controler(entrees, referentiel)
    alertes = [a for e in entrees if (a := etat_effectif(e).alerte)]
    if problemes:
        st.error(
            "\n".join(f"- {p}" for p in problemes),
            title="Contrôles §9 : problèmes bloquants",
            icon=":material/error:",
        )
    else:
        st.success("Contrôles §9 : aucun problème bloquant.", icon=":material/check_circle:")
    if alertes:
        with st.expander(f"Alertes ({len(alertes)})", icon=":material/warning:"):
            st.markdown("\n".join(f"- {a}" for a in alertes))
    if entrees:
        st.dataframe(
            [
                {
                    "Id": e.id,
                    "Type": LIBELLES_TYPES[e.type],
                    "HE": _nom_he(referentiel, e.he_id),
                    "Voie": LIBELLES_VOIES[e.voie] if e.voie else None,
                    "Population": LIBELLES_AGES[e.population] if e.population else None,
                    "Valeur": _resume_valeur(e),
                    "Source": f"p. {e.source.page} — {e.source.localisation}",
                    "Statut": str(e.statut),
                    "Appliquée": etat_effectif(e).applique,
                }
                for e in entrees
            ],
            hide_index=True,
            alt="Entrées de la table de sécurité",
        )


def _index(options: list[Any], valeur: Any) -> int | None:
    return options.index(valeur) if valeur in options else None


def _texte(valeur: str) -> str | None:
    return valeur.strip() or None


def _formulaire_entree(entree: EntreeSecurite | None, referentiel: Referentiel) -> None:
    cle = entree.id if entree else NOUVELLE
    huiles = [TOUTES_HE, *sorted(h.id for h in referentiel)]
    profils = [*ProfilRisque, *TrancheAge]
    with st.form(f"entree_{cle}", border=True):
        st.markdown("**:material/edit: Champs de fond**")
        st.caption(
            "Obligatoires selon le type — plafond : voie, population, valeur, unité ; "
            "plafond total : HE « * » + les mêmes ; drapeau : drapeau (+ détail pour une "
            "interaction médicamenteuse) ; contre-indication : profil. Nom latin requis "
            "sauf pour « * »."
        )
        colonne_a, colonne_b = st.columns(2)
        with colonne_a:
            type_ = st.selectbox(
                "Type",
                list(TypeEntree),
                index=_index(list(TypeEntree), entree.type if entree else TypeEntree.PLAFOND),
                format_func=lambda t: LIBELLES_TYPES[t],
            )
            he_id = st.selectbox(
                "Huile essentielle",
                huiles,
                index=_index(huiles, entree.he_id) if entree else None,
                format_func=lambda h: _nom_he(referentiel, h),
                placeholder="Choisir…",
            )
            nom_latin = st.text_input(
                "Nom latin (tel qu'écrit dans la source)",
                value=(entree.nom_latin or "") if entree else "",
            )
            chemotype = st.text_input(
                "Chémotype (vide si la source n'en cite pas)",
                value=(entree.chemotype or "") if entree else "",
            )
            voie = st.selectbox(
                "Voie",
                list(Voie),
                index=_index(list(Voie), entree.voie) if entree else None,
                format_func=lambda v: LIBELLES_VOIES[v],
                placeholder="—",
            )
            population = st.selectbox(
                "Population",
                list(TrancheAge),
                index=_index(list(TrancheAge), entree.population) if entree else None,
                format_func=lambda a: LIBELLES_AGES[a],
                placeholder="—",
            )
        with colonne_b:
            with st.container(horizontal=True):
                valeur = st.number_input(
                    "Valeur",
                    min_value=0.0,
                    value=entree.valeur if entree else None,
                    step=0.1,
                    format="%.4g",
                )
                unite = st.text_input("Unité", value=(entree.unite or "") if entree else "%")
            base = st.selectbox(
                "Base du pourcentage",
                ["p/p", "v/v"],
                index=_index(["p/p", "v/v"], entree.base_pourcentage) if entree else None,
                placeholder="Non précisée",
            )
            drapeau = st.selectbox(
                "Drapeau",
                list(Drapeau),
                index=_index(list(Drapeau), entree.drapeau) if entree else None,
                placeholder="—",
            )
            profil = st.selectbox(
                "Profil contre-indiqué",
                profils,
                index=_index(profils, entree.profil) if entree else None,
                format_func=lambda p: LIBELLES_PROFILS.get(p, str(p)),
                placeholder="—",
            )
            detail = st.text_input("Détail", value=(entree.detail or "") if entree else "")

        st.markdown("**:material/menu_book: Source**")
        colonne_a, colonne_b = st.columns([3, 1])
        ouvrage = colonne_a.text_input(
            "Ouvrage", value=entree.source.ouvrage if entree else OUVRAGE_PRIMAIRE
        )
        page = colonne_b.text_input("Page", value=str(entree.source.page) if entree else "")
        localisation = st.text_input(
            "Localisation",
            value=entree.source.localisation if entree else "",
            placeholder="ex. Monographie Lavender, Safety summary",
        )
        citation = st.text_area(
            "Citation exacte (langue d'origine)", value=entree.source.citation if entree else ""
        )
        interpretation = st.text_area(
            "Interprétation (vide si recopie telle quelle ; sinon règle(s) R… + explication)",
            value=(entree.interpretation or "") if entree else "",
        )

        st.markdown("**:material/person_edit: Saisie**")
        with st.container(horizontal=True):
            par = st.text_input(
                "Saisie par", value=entree.saisie.par if entree else get_settings().utilisateur
            )
            le = st.date_input(
                "Le", value=entree.saisie.le if entree else date.today(), format="DD/MM/YYYY"
            )
            methode = st.selectbox(
                "Méthode",
                ["manuelle", "assistee"],
                index=["manuelle", "assistee"].index(
                    entree.saisie.methode if entree else "manuelle"
                ),
                format_func=lambda m: "Manuelle" if m == "manuelle" else "Assistée (R13)",
            )
        if entree is not None and entree.statut in (Statut.VERIFIE, Statut.VALIDE):
            st.caption(
                ":material/warning: Modifier un champ de fond ramène l'entrée en brouillon "
                "(vérification et validation à refaire)."
            )
        libelle = "Créer l'entrée" if entree is None else "Enregistrer"
        if st.form_submit_button(libelle, type="primary", icon=":material/save:"):
            donnees: dict[str, Any] = {
                "type": type_,
                "he_id": he_id,
                "nom_latin": _texte(nom_latin),
                "chemotype": _texte(chemotype),
                "voie": voie,
                "population": population,
                "valeur": valeur,
                "unite": _texte(unite),
                "base_pourcentage": base,
                "drapeau": drapeau,
                "profil": profil,
                "detail": _texte(detail),
                "source": {
                    "ouvrage": ouvrage,
                    "page": int(page) if page.strip().isdigit() else page.strip(),
                    "localisation": localisation,
                    "citation": citation,
                },
                "interpretation": _texte(interpretation),
                "saisie": {"par": par, "le": le, "methode": methode},
            }
            if entree is not None:
                donnees["id"] = entree.id
            try:
                enregistree = enregistrer_entree(dossier(), donnees)
            except ErreurAdmin as exc:
                st.error(str(exc), title="Enregistrement refusé", icon=":material/error:")
            else:
                st.session_state["entree_a_choisir"] = enregistree.id
                _apres_ecriture(f"{enregistree.id} : enregistrée ({enregistree.statut}).")


def _suivi_entree(entree: EntreeSecurite) -> None:
    etat = etat_effectif(entree)
    v, val = entree.verification, entree.validation
    st.markdown("**:material/lock: Suivi (lecture seule)**")
    st.table(
        {
            "Identifiant": f"`{entree.id}`",
            "Statut": LIBELLES_STATUTS[entree.statut],
            "Appliquée par l'outil": "oui" if etat.applique else "non",
            "Empreinte actuelle": f"`{empreinte(entree)[:16]}…`",
            "Vérifiée par": _ou_tiret(v.par),
            "Vérifiée le": _ou_tiret(v.le),
            "Résultat": _ou_tiret(v.resultat),
            "Commentaire": _ou_tiret(v.commentaire),
            "Empreinte vérifiée": f"`{v.empreinte[:16]}…`" if v.empreinte else "—",
            "Validée par": _ou_tiret(val.par),
            "Validée le": _ou_tiret(val.le),
            "Empreinte validée": f"`{val.empreinte[:16]}…`" if val.empreinte else "—",
            "Motif de retrait": _ou_tiret(entree.motif_retrait),
        },
        border="horizontal",
    )
    if etat.alerte:
        st.warning(etat.alerte, icon=":material/warning:")


def _ecrire_cycle(entree: EntreeSecurite, message: str) -> None:
    remplacer_entree(dossier(), entree)
    _apres_ecriture(message)


def _actions_cycle(entree: EntreeSecurite) -> None:
    if entree.statut == Statut.RETIRE:
        st.caption(":material/block: Entrée retirée : plus aucune action possible (règle P6).")
        return
    utilisateur = get_settings().utilisateur
    st.markdown("**:material/published_with_changes: Cycle de vie**")
    verification, validation, retrait = st.tabs(
        [
            ":material/fact_check: Vérifier",
            ":material/verified: Valider",
            ":material/block: Retirer",
        ]
    )
    with verification, st.form(f"verifier_{entree.id}", border=False):
        st.caption("Comparer l'entrée au livre (checklist §8), lors d'une session distincte.")
        par = st.text_input("Par", value=utilisateur, key=f"verif_par_{entree.id}")
        le = st.date_input(
            "Le", value=date.today(), format="DD/MM/YYYY", key=f"verif_le_{entree.id}"
        )
        conforme = st.toggle("Checklist entièrement conforme", key=f"verif_ok_{entree.id}")
        commentaire = st.text_input("Commentaire (obligatoire si non conforme)")
        if st.form_submit_button("Enregistrer la vérification", icon=":material/fact_check:"):
            try:
                nouvelle = verifier(entree, par, le, conforme, _texte(commentaire))
            except ErreurCycle as exc:
                st.error(str(exc), icon=":material/error:")
            else:
                _ecrire_cycle(nouvelle, f"{entree.id} : vérification enregistrée.")
    with validation:
        if entree.statut != Statut.VERIFIE:
            st.caption("Seule une entrée vérifiée conforme peut être validée.")
        else:
            with st.form(f"valider_{entree.id}", border=False):
                par = st.text_input("Par", value=utilisateur, key=f"valid_par_{entree.id}")
                le = st.date_input(
                    "Le", value=date.today(), format="DD/MM/YYYY", key=f"valid_le_{entree.id}"
                )
                if st.form_submit_button("Valider", type="primary", icon=":material/verified:"):
                    try:
                        nouvelle = valider(entree, par, le)
                    except ErreurCycle as exc:
                        st.error(str(exc), icon=":material/error:")
                    else:
                        _ecrire_cycle(nouvelle, f"{entree.id} : validée.")
    with retrait, st.form(f"retirer_{entree.id}", border=False):
        st.caption("Une entrée erronée n'est jamais supprimée : elle est retirée avec un motif.")
        motif = st.text_input("Motif du retrait", key=f"motif_{entree.id}")
        if st.form_submit_button("Retirer l'entrée", icon=":material/block:"):
            try:
                nouvelle = retirer(entree, motif, date.today())
            except ErreurCycle as exc:
                st.error(str(exc), icon=":material/error:")
            else:
                _ecrire_cycle(nouvelle, f"{entree.id} : retirée.")


def page_securite() -> None:
    _afficher_message()
    st.caption("Saisie, vérification et validation de `data/securite.yaml`.")
    with st.container(horizontal=True, vertical_alignment="center"):
        st.warning(
            "Aucune valeur ne doit provenir d'un LLM, de la mémoire ou d'un site non listé "
            "(règle P3) : uniquement Essential Oil Safety, page et citation exacte à l'appui.",
            icon=":material/health_and_safety:",
            width="stretch",
        )
        st.link_button("Lire la règle", URL_REGLE, icon=":material/open_in_new:")
    try:
        entrees = lire_securite(dossier())
        referentiel = _referentiel()
    except (OSError, ValueError) as exc:
        st.error(str(exc), title="Fichier illisible", icon=":material/error:")
        return
    _vue_ensemble_securite(entrees, referentiel)
    if not entrees:
        st.info(
            "Table vide : l'outil ne propose aucun dosage (fail closed, règle P4).",
            icon=":material/info:",
        )

    st.subheader("Saisie", icon=":material/edit_note:")
    options = [NOUVELLE, *(e.id for e in entrees)]
    par_id = {e.id: e for e in entrees}
    if "entree_a_choisir" in st.session_state:
        st.session_state["entree_choisie"] = st.session_state.pop("entree_a_choisir")
    if st.session_state.get("entree_choisie") not in options:
        st.session_state["entree_choisie"] = NOUVELLE
    choix = st.selectbox(
        "Entrée",
        options,
        key="entree_choisie",
        format_func=lambda i: (
            "Nouvelle entrée"
            if i == NOUVELLE
            else f"{i} — {LIBELLES_TYPES[par_id[i].type]} — {_nom_he(referentiel, par_id[i].he_id)}"
        ),
    )
    entree = par_id.get(choix)
    if entree is None:
        _formulaire_entree(None, referentiel)
        return
    colonne_saisie, colonne_suivi = st.columns([3, 2], gap="large")
    with colonne_saisie:
        if entree.statut == Statut.RETIRE:
            st.json(entree.model_dump(mode="json"), expanded=True)
        else:
            _formulaire_entree(entree, referentiel)
    with colonne_suivi:
        _suivi_entree(entree)
        _actions_cycle(entree)
