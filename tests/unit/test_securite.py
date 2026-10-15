from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_he.models import Drapeau, TrancheAge, Voie
from agent_he.referentiel.rapport import rapport_markdown
from agent_he.referentiel.securite import (
    ErreurCycle,
    ProfilRisque,
    Statut,
    TableSecurite,
    controler,
    ecrire_entrees,
    empreinte,
    etat_effectif,
    lire_entrees,
    valider,
    verifier,
)

from aides import (
    DOSSIER_DONNEES,
    drapeau,
    entree,
    interdit,
    plafond,
    plafond_total,
    referentiel,
)

REF = referentiel()
ADULTE = TrancheAge.ADULTE
CUTANEE = Voie.CUTANEE


# --- Données réelles -----------------------------------------------------------------


def test_table_du_depot_conforme() -> None:
    """Bloquant en CI : data/securite.yaml respecte les contrôles du §9."""
    entrees = lire_entrees(DOSSIER_DONNEES / "securite.yaml")
    assert controler(entrees, REF) == []


# --- Schéma (§4) -----------------------------------------------------------------------


def test_entree_sans_citation_refusee() -> None:
    with pytest.raises(ValidationError):
        entree(
            statut="brouillon",
            source={"ouvrage": "x", "page": 1, "localisation": "x", "citation": "  "},
        )
    with pytest.raises(ValidationError):
        entree(statut="brouillon", source={"ouvrage": "x", "page": 1, "localisation": "x"})


@pytest.mark.parametrize(
    "champs",
    [
        {"valeur": None},
        {"voie": None},
        {"valeur": 150},
        {"valeur": 0},
        {"voie": "orale"},
        {"type": "drapeau", "drapeau": None},
        {"type": "drapeau", "drapeau": "interaction_medicament"},  # sans detail
        {"type": "interdit_profil"},
        {"type": "plafond_total"},  # he_id doit être "*"
        {"he_id": "*"},  # plafond sur toutes les HE
        {"nom_latin": None},
        {"id": "SEC-1"},
        {"inconnu": 1},
    ],
)
def test_schema_invalide(champs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        entree(statut="brouillon", **champs)


# --- Contrôles (§9) ----------------------------------------------------------------


def test_he_inconnue_detectee() -> None:
    e = entree(statut="brouillon", he_id="licorne", nom_latin="Unicornus")
    assert any("HE inconnue" in p for p in controler([e], REF))


def test_nom_latin_incoherent_detecte() -> None:
    e = entree(statut="brouillon", nom_latin="Lavandula latifolia")
    assert any("incohérent" in p for p in controler([e], REF))


def test_identifiant_en_double_detecte() -> None:
    a = entree(statut="brouillon")
    assert any("double" in p for p in controler([a, a], REF))


def test_valide_sans_verification_detecte() -> None:
    e = entree(statut="brouillon").model_copy(update={"statut": Statut.VALIDE})
    problemes = controler([e], REF)
    assert any("sans vérification conforme" in p for p in problemes)


def test_verifie_non_conforme_detecte() -> None:
    e = entree(statut="verifie")
    e.verification.resultat = "non_conforme"
    assert any("sans vérification conforme" in p for p in controler([e], REF))


def test_valide_empreinte_alteree_detectee() -> None:
    e = entree(statut="valide")
    e.valeur = 50
    assert any("empreinte" in p for p in controler([e], REF))


def test_dates_incoherentes_detectees() -> None:
    e = entree(statut="valide")
    e.verification.le = date(2025, 1, 1)
    problemes = controler([e], REF)
    assert any("vérification antérieure" in p for p in problemes)


def test_retrait_sans_motif_detecte() -> None:
    e = entree(statut="brouillon").model_copy(update={"statut": Statut.RETIRE})
    assert any("motif" in p for p in controler([e], REF))


def test_unite_non_pourcentage_jamais_validable() -> None:
    e = entree(statut="brouillon", unite="gouttes/ml")
    e = verifier(e, par="relecteur", le=date(2026, 1, 2), conforme=True)
    assert any("R12" in p for p in controler([e], REF))
    with pytest.raises(ErreurCycle):
        valider(e, par="moi", le=date(2026, 1, 3))


def test_entrees_correctes_sans_probleme() -> None:
    entrees = [
        entree(statut="brouillon"),
        entree(statut="verifie"),
        entree(statut="valide"),
        entree(statut="retire"),
        plafond_total(5),
        drapeau("gaultherie", "interaction_medicament", detail="anticoagulants"),
    ]
    assert controler(entrees, REF) == []


# --- Application selon le statut (§6) ----------------------------------------------


@pytest.mark.parametrize("statut", ["brouillon", "verifie", "retire"])
def test_plafond_non_valide_jamais_applique(statut: str) -> None:
    table = TableSecurite([plafond("lavande_vraie", 5, statut=statut)])
    assert table.plafond("lavande_vraie", CUTANEE, ADULTE) is None


def test_plafond_valide_applique() -> None:
    table = TableSecurite([plafond("lavande_vraie", 5)])
    assert table.plafond("lavande_vraie", CUTANEE, ADULTE) == 5


@pytest.mark.parametrize("statut", ["brouillon", "verifie", "valide"])
def test_drapeau_applique_des_la_saisie(statut: str) -> None:
    table = TableSecurite([drapeau("bergamote", "phototoxique", statut=statut)])
    assert table.drapeaux("bergamote") == {Drapeau.PHOTOTOXIQUE}
    assert (statut != "valide") == any("non validé" in a for a in table.alertes)


def test_interdit_brouillon_applique() -> None:
    table = TableSecurite([interdit("sauge_officinale", "epilepsie", statut="brouillon")])
    assert table.he_interdites(ProfilRisque.EPILEPSIE) == {"sauge_officinale"}
    assert table.profils_interdits("sauge_officinale") == {ProfilRisque.EPILEPSIE}


def test_entree_retiree_ignoree() -> None:
    table = TableSecurite([drapeau("bergamote", "phototoxique", statut="retire")])
    assert table.drapeaux("bergamote") == set()


def test_modification_apres_validation_rend_inutilisable() -> None:
    e = plafond("lavande_vraie", 5)
    e.valeur = 30  # modification d'un champ de fond
    table = TableSecurite([e])
    assert table.plafond("lavande_vraie", CUTANEE, ADULTE) is None
    assert any("empreinte invalide" in a for a in table.alertes)


def test_modification_citation_rend_inutilisable() -> None:
    e = plafond("lavande_vraie", 5)
    e.source.citation = "autre citation"
    assert not etat_effectif(e).applique


def test_modification_suivi_ne_change_pas_l_empreinte() -> None:
    e = plafond("lavande_vraie", 5)
    avant = empreinte(e)
    e.saisie.par = "quelqu'un d'autre"
    e.motif_retrait = "rien"
    assert empreinte(e) == avant
    assert etat_effectif(e).applique


def test_drapeau_altere_reste_applique_avec_alerte() -> None:
    e = drapeau("bergamote", "phototoxique")
    e.detail = "modifié"
    table = TableSecurite([e])
    assert table.drapeaux("bergamote") == {Drapeau.PHOTOTOXIQUE}
    assert any("empreinte invalide" in a for a in table.alertes)


# --- Plafonds -----------------------------------------------------------------------


def test_plafond_le_plus_restrictif() -> None:
    table = TableSecurite([plafond("lavande_vraie", 5), plafond("lavande_vraie", 3)])
    assert table.plafond("lavande_vraie", CUTANEE, ADULTE) == 3


def test_plafond_sans_extrapolation_voie_ni_population() -> None:
    table = TableSecurite([plafond("lavande_vraie", 5)])
    assert table.plafond("lavande_vraie", Voie.BAIN, ADULTE) is None
    assert table.plafond("lavande_vraie", CUTANEE, TrancheAge.DE_6_A_12) is None


def test_plafond_par_chemotype() -> None:
    table = TableSecurite([plafond("lavande_vraie", 5, chemotype="linalol")])
    assert table.plafond("lavande_vraie", CUTANEE, ADULTE, chemotype="linalol") == 5
    assert table.plafond("lavande_vraie", CUTANEE, ADULTE) is None


def test_plafond_effectif() -> None:
    table = TableSecurite([plafond("lavande_vraie", 5), plafond_total(3)])
    assert table.plafond_effectif("lavande_vraie", CUTANEE, ADULTE) == 3
    # R8 : sans plafond propre, le plafond total de la voie s'applique.
    assert table.plafond_effectif("orange_douce", CUTANEE, ADULTE) == 3
    assert TableSecurite([]).plafond_effectif("lavande_vraie", CUTANEE, ADULTE) is None


# --- Cycle de vie -------------------------------------------------------------------


def test_cycle_complet() -> None:
    e = entree(statut="brouillon")
    v = verifier(e, par="relecteur", le=date(2026, 1, 2), conforme=True)
    assert v.statut == Statut.VERIFIE
    assert v.verification.empreinte == empreinte(e)
    ok = valider(v, par="moi", le=date(2026, 1, 3))
    assert ok.statut == Statut.VALIDE
    assert etat_effectif(ok).valide


def test_verification_meme_session_refusee() -> None:
    e = entree(statut="brouillon")
    with pytest.raises(ErreurCycle):
        verifier(e, par="testeur", le=date(2026, 1, 1), conforme=True)


def test_non_conforme_reste_brouillon() -> None:
    e = entree(statut="brouillon")
    with pytest.raises(ErreurCycle):
        verifier(e, par="relecteur", le=date(2026, 1, 2), conforme=False)
    v = verifier(e, par="relecteur", le=date(2026, 1, 2), conforme=False, commentaire="page")
    assert v.statut == Statut.BROUILLON
    with pytest.raises(ErreurCycle):
        valider(v, par="moi", le=date(2026, 1, 3))


def test_validation_refusee_si_modifiee_apres_verification() -> None:
    v = entree(statut="verifie")
    v.valeur = 9
    with pytest.raises(ErreurCycle):
        valider(v, par="moi", le=date(2026, 1, 3))


def test_validation_refusee_avant_verification() -> None:
    v = entree(statut="verifie")
    with pytest.raises(ErreurCycle):
        valider(v, par="moi", le=date(2025, 12, 31))


def test_aller_retour_fichier(tmp_path: Path) -> None:
    chemin = tmp_path / "securite.yaml"
    chemin.write_text("# entête\n[]\n", encoding="utf-8")
    entrees = [plafond("lavande_vraie", 5), drapeau("bergamote", "phototoxique")]
    ecrire_entrees(chemin, entrees, entete="# entête\n")
    relues = lire_entrees(chemin)
    assert relues == entrees
    assert all(etat_effectif(e).valide for e in relues)
    assert chemin.read_text(encoding="utf-8").startswith("# entête\n")


# --- Rapport ------------------------------------------------------------------------


def test_rapport() -> None:
    entrees = [
        plafond("lavande_vraie", 5),
        entree(statut="brouillon", interpretation="R2 : borne basse de la fourchette"),
        drapeau("bergamote", "phototoxique"),
    ]
    texte = rapport_markdown(TableSecurite(entrees), REF, date(2026, 10, 15))
    assert "# Audit de la table de sécurité — 2026-10-15" in texte
    assert "valeur fictive de test" in texte
    assert "Aucun problème bloquant" in texte
    assert "statut brouillon" in texte
    assert "R2 : borne basse" in texte
    assert "**tea_tree** : aucune voie ni population couverte" in texte
    assert "cutanee/adulte" not in texte.split("**lavande_vraie** :")[1].split("\n")[0]
