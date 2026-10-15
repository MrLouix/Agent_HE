from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agent_he.journal.ranking import BORNE, classer, score_journal
from agent_he.journal.repository import ErreurJournal, Journal
from agent_he.journal.saisie import parser_melange, utilisations_sans_retour
from agent_he.journal.stats import (
    preferences_olfactives,
    rappel,
    stats_par_he,
    stats_recette,
)
from agent_he.journal.tolerance import he_suspectes, propositions_exclusion, suspectes_pour
from agent_he.models import Demande, EntreeUsage, ExclusionPerso, Fiche, Voie
from agent_he.storage.db import connecter
from agent_he.storage.favorites import Historique

from aides import (
    dose,
    questionnaire,
    recette,
    referentiel,
)


@pytest.fixture
def journal() -> Journal:
    return Journal(connecter(":memory:"))


def usage(**champs: Any) -> EntreeUsage:
    valeurs: dict[str, Any] = {"recette_ref": "r1", "voie": "cutanee", "tolerance": "aucune"}
    valeurs.update(champs)
    return EntreeUsage.model_validate(valeurs)


# --- Dépôt -----------------------------------------------------------------------------


def test_crud(journal: Journal) -> None:
    eid = journal.ajouter(usage(efficacite=4), ["lavande_vraie"])
    assert journal.obtenir(eid).efficacite == 4
    assert journal.huiles(eid) == ["lavande_vraie"]
    modifiee = journal.modifier(
        eid, tolerance="legere", description_reaction="rougeur le lendemain"
    )
    assert modifiee.tolerance == "legere"
    assert journal.obtenir(eid).description_reaction == "rougeur le lendemain"
    with pytest.raises(ErreurJournal):
        journal.modifier(eid, recette_ref="autre")
    with pytest.raises(ValueError):
        journal.modifier(eid, efficacite=9)
    journal.supprimer(eid)
    with pytest.raises(ErreurJournal):
        journal.obtenir(eid)


def test_melange_libre(journal: Journal) -> None:
    doses = parser_melange("lavande fine:3:gouttes ; Citrus sinensis:2,5:gtt", referentiel())
    assert [(d.he_id, d.quantite.valeur, d.quantite.unite) for d in doses] == [
        ("lavande_vraie", 3, "gouttes"),
        ("orange_douce", 2.5, "gouttes"),
    ]
    assert all(d.sources == [] for d in doses)
    eid = journal.ajouter(EntreeUsage(melange_libre=doses, voie=Voie.CUTANEE, tolerance="aucune"))
    assert journal.huiles(eid) == ["lavande_vraie", "orange_douce"]


@pytest.mark.parametrize("texte", ["", "licorne:3:gouttes", "lavande fine:3", "lavande fine:x:ml"])
def test_melange_libre_invalide(texte: str) -> None:
    with pytest.raises(ErreurJournal):
        parser_melange(texte, referentiel())


def test_entree_sans_huile_refusee(journal: Journal) -> None:
    with pytest.raises(ErreurJournal):
        journal.ajouter(usage())


def test_filtres(journal: Journal) -> None:
    journal.ajouter(usage(), ["lavande_vraie"])
    journal.ajouter(usage(recette_ref="r2"), ["orange_douce"])
    assert len(journal.lister(recette_ref="r2")) == 1
    assert len(journal.lister(he_id="lavande_vraie")) == 1
    assert journal.lister(depuis=datetime.now(UTC) + timedelta(days=1)) == []


# --- Statistiques ------------------------------------------------------------------------


def _jeu() -> list[tuple[EntreeUsage, list[str]]]:
    """Jeu d'entrées connu : la cannelle est l'HE suspecte."""
    return [
        (usage(efficacite=5, odeur=5), ["lavande_vraie", "orange_douce"]),
        (usage(efficacite=3, odeur=4, tolerance="legere"), ["lavande_vraie", "cannelle_ecorce"]),
        (usage(recette_ref="r2", odeur=1, tolerance="forte"), ["cannelle_ecorce", "girofle"]),
        (usage(recette_ref="r3", odeur=2), ["girofle"]),
    ]


def test_stats_recette_et_rappel() -> None:
    stats = stats_recette(_jeu(), "r1")
    assert stats is not None
    assert (stats.nb_usages, stats.efficacite_moy, stats.odeur_moy) == (2, 4, 4.5)
    assert len(stats.reactions) == 1
    assert rappel(stats) == "d'après ton journal : utilisée 2 fois, efficacité 4/5, odeur 4.5/5"
    assert stats_recette(_jeu(), "inconnue") is None
    assert rappel(None) is None


def test_stats_par_he() -> None:
    stats = stats_par_he(_jeu())
    assert stats["lavande_vraie"].nb_usages == 2
    assert stats["cannelle_ecorce"].nb_reactions_fortes == 1
    assert stats["cannelle_ecorce"].nb_reactions_legeres == 1


def test_preferences_olfactives() -> None:
    prefs = preferences_olfactives(_jeu())
    assert prefs.appreciees == ["lavande_vraie", "orange_douce"]
    assert prefs.detestees == ["girofle"]  # cannelle : (4 + 1) / 2 = 2,5 > 2


# --- Tolérance -----------------------------------------------------------------------------


def test_he_suspectes_sur_un_jeu_connu() -> None:
    suspectes = he_suspectes(_jeu())
    # lavande et girofle figurent dans des mélanges bien tolérés : pas suspectes.
    assert [s.he_id for s in suspectes] == ["cannelle_ecorce"]
    assert (suspectes[0].nb_fortes, suspectes[0].nb_legeres) == (1, 1)
    entree_reaction = _jeu()[1][0]
    jeu = [_jeu()[0], (entree_reaction, ["lavande_vraie", "cannelle_ecorce"])]
    assert suspectes_pour(jeu, entree_reaction.id) == ["cannelle_ecorce"]


def test_seuil_donne_une_proposition_pas_une_exclusion(journal: Journal) -> None:
    for entree, huiles in _jeu():
        journal.ajouter(entree, huiles)
    propositions = propositions_exclusion(journal.lister(), set(journal.exclusions()))
    assert [p.he_id for p in propositions] == ["cannelle_ecorce"]
    assert journal.exclusions() == {}  # rien n'est exclu sans confirmation
    p = propositions[0]
    journal.confirmer_exclusion(
        ExclusionPerso(he_id=p.he_id, motif=p.motif, entrees_liees=list(p.entrees))
    )
    assert "cannelle_ecorce" in journal.exclusions()
    assert propositions_exclusion(journal.lister(), set(journal.exclusions())) == []
    journal.retirer_exclusion("cannelle_ecorce")
    assert journal.exclusions() == {}


def test_seuil_configurable() -> None:
    une_legere = [(usage(tolerance="legere"), ["ylang_ylang"])]
    assert propositions_exclusion(une_legere, set()) == []
    assert [p.he_id for p in propositions_exclusion(une_legere, set(), seuil_legeres=1)] == [
        "ylang_ylang"
    ]


# --- Classement ---------------------------------------------------------------------------


def test_classement_borne_et_sans_filtrage() -> None:
    bien = recette(dose("lavande_vraie", 2), nom_recette="r1")
    mal = recette(dose("cannelle_ecorce", 1), nom_recette="r2")
    jeu = _jeu()
    assert -BORNE <= score_journal(mal, "r2", jeu) < 0 < score_journal(bien, "r1", jeu) <= BORNE
    candidates = [(mal, "r2", 0.9), (bien, "r1", 0.85)]
    ordonnees = classer(candidates, jeu, lambda c: c[0], lambda c: c[1], lambda c: c[2])
    assert [c[1] for c in ordonnees] == ["r1", "r2"]
    assert sorted(ordonnees, key=id) == sorted(candidates, key=id)  # rien d'ajouté ni retiré
    assert classer([], jeu, lambda c: c[0], lambda c: c[1], lambda c: c[2]) == []


def test_dix_retours_parfaits_ne_depassent_pas_la_borne() -> None:
    r = recette(dose("lavande_vraie", 2), nom_recette="r1")
    jeu = [(usage(efficacite=5, odeur=5), ["lavande_vraie"]) for _ in range(10)]
    assert score_journal(r, "r1", jeu) <= BORNE


# --- Rappels -----------------------------------------------------------------------------


def test_utilisations_sans_retour(journal: Journal) -> None:
    historique = Historique(journal._db)
    fiche = Fiche(
        mode="publiee", recette=recette(dose("lavande_vraie", 2)), convention_gouttes_ml=20
    )
    demande = Demande(besoin="dormir", voies=["cutanee"], questionnaire=questionnaire())
    historique.ajouter(demande, fiche, [], "roll-on")
    assert utilisations_sans_retour(historique, journal) == ["roll-on"]
    journal.ajouter(usage(recette_ref="roll-on"), ["lavande_vraie"])
    assert utilisations_sans_retour(historique, journal) == []
