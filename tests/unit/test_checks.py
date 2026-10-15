"""Tests obligatoires de la phase 2 : ils ne seront jamais désactivés."""

from typing import Any

import pytest

from agent_he.models import AVERTISSEMENT_SYNTHESE, Fiche, Recette
from agent_he.referentiel.securite import TableSecurite
from agent_he.safety.checks import (
    FicheNonSure,
    IndicationSource,
    Verdict,
    assert_fiche_sure,
    controler_recette,
)
from agent_he.safety.questionnaire import he_a_eviter, profil_exclu

from aides import URL_A, dose, questionnaire, recette, referentiel, table_test

REF = referentiel()
TABLE = table_test()


def controler(r: Recette, table: TableSecurite = TABLE, **kwargs: Any) -> Verdict:
    q = kwargs.pop("q", questionnaire())
    return controler_recette(r, q, table, REF, convention_gouttes_ml=20, **kwargs)


def fiche(r: Recette, mode: str = "publiee", **champs: Any) -> Fiche:
    return Fiche.model_validate(
        {"mode": mode, "recette": r.model_dump(), "convention_gouttes_ml": 20, **champs}
    )


# --- Profils exclus ⇒ refus -------------------------------------------------------------


@pytest.mark.parametrize(
    "champs",
    [{"grossesse_allaitement": True}, {"epilepsie": True}, {"asthme": True}, {"age": "de_3_a_6"}],
)
def test_profil_exclu_refus_sans_quantite(champs: dict[str, Any]) -> None:
    q = questionnaire(**champs)
    verdict = controler(recette(dose("lavande_vraie", 2)), q=q)
    assert not verdict.conforme
    assert verdict.recette is None
    motif = profil_exclu(q)
    assert motif is not None
    refus = Fiche(
        mode="refus", motif=motif.texte, he_a_eviter=he_a_eviter(q, TABLE), convention_gouttes_ml=20
    )
    assert refus.he_a_eviter
    assert_fiche_sure(refus, q, TABLE, REF)
    with pytest.raises(FicheNonSure):
        assert_fiche_sure(fiche(recette(dose("lavande_vraie", 2))), q, TABLE, REF)


def test_traitement_exclut_interaction_medicament() -> None:
    q = questionnaire(traitement=True)
    verdict = controler(recette(dose("gaultherie", 2), dose("lavande_vraie", 2)), q=q)
    assert not verdict.conforme
    assert any("interaction" in r for r in verdict.rejets)
    assert controler(recette(dose("lavande_vraie", 2)), q=q).conforme


def test_pathologie_hormonale_exclut_hormone_like() -> None:
    q = questionnaire(pathologie_hormonale=True)
    assert not controler(recette(dose("sauge_sclaree", 2)), q=q).conforme


# --- Plafonds -----------------------------------------------------------------------------


def test_recette_conforme() -> None:
    verdict = controler(recette(dose("lavande_vraie", 6), dose("orange_douce", 4)))
    assert verdict.conforme, verdict.rejets
    assert verdict.recette is not None
    assert [h.concentration_pct for h in verdict.recette.huiles] == [3, 2]
    assert_fiche_sure(fiche(verdict.recette), questionnaire(), TABLE, REF)


def test_verbatim_au_dessus_du_plafond_rejetee_sans_correction() -> None:
    r = recette(dose("lavande_vraie", 12))  # 6 % > 5 %
    verdict = controler(r)
    assert not verdict.conforme
    assert verdict.recette is None
    assert "plafond_he" in verdict.controles
    with pytest.raises(FicheNonSure):
        assert_fiche_sure(fiche(r), questionnaire(), TABLE, REF)


def test_plafond_exact_accepte() -> None:
    assert controler(recette(dose("lavande_vraie", 10))).conforme  # 5 % = plafond


def test_total_au_dessus_du_plafond_total_rejete() -> None:
    # 4 % + 3,5 % : chacune sous son plafond, total 7,5 % > 6 %
    r = recette(dose("lavande_vraie", 8), dose("orange_douce", 7))
    verdict = controler(r)
    assert not verdict.conforme
    assert verdict.controles == ["plafond_total"]


def test_he_absente_de_la_table_aucun_dosage() -> None:
    verdict = controler(recette(dose("ylang_ylang", 1)))
    assert not verdict.conforme
    assert "fail_closed" in verdict.controles


def test_he_sans_plafond_pour_la_voie() -> None:
    verdict = controler(recette(dose("tea_tree", 1), voie="bain"))
    assert not verdict.conforme


def test_population_sans_valeur_pediatrique_refusee() -> None:
    q = questionnaire(age="de_6_a_12")
    assert controler(recette(dose("lavande_vraie", 2)), q=q).conforme  # 1 % ≤ 2 %
    assert not controler(recette(dose("lavande_vraie", 6)), q=q).conforme  # 3 % > 2 %
    # R7 + R8 : sans plafond pédiatrique propre, seul le plafond total 6–12 ans validé
    # s'applique (0,5 % ≤ 3 %) ; il n'y a aucune extrapolation depuis la valeur adulte.
    assert controler(recette(dose("orange_douce", 1)), q=q).conforme
    assert not controler(recette(dose("orange_douce", 8)), q=q).conforme  # 4 % > 3 %


def test_concentration_non_calculable_rejetee() -> None:
    verdict = controler(recette(dose("lavande_vraie", 2), base_volume_ml=None))
    assert not verdict.conforme
    assert "concentration_inconnue" in verdict.controles


def test_table_vide_aucun_dosage() -> None:
    assert not controler(recette(dose("lavande_vraie", 1)), table=TableSecurite([])).conforme


def test_plafond_non_valide_ignore() -> None:
    from aides import drapeau, plafond, plafond_total

    # Un plafond seulement vérifié ne compte pas : l'HE n'est pas couverte par la table.
    table = TableSecurite([plafond("lavande_vraie", 1, statut="verifie"), plafond_total(6)])
    assert not controler(recette(dose("lavande_vraie", 4)), table=table).conforme
    # Couverte par une autre entrée validée : R8, le plafond total validé s'applique
    # (le plafond « verifie » de 1 % reste ignoré).
    table = TableSecurite([*table.entrees, drapeau("lavande_vraie", "allergene")])
    assert controler(recette(dose("lavande_vraie", 4)), table=table).conforme
    table_sans_total = TableSecurite([plafond("lavande_vraie", 5, statut="verifie")])
    assert not controler(recette(dose("lavande_vraie", 1)), table=table_sans_total).conforme


def test_he_couverte_par_brouillon_seulement_refusee() -> None:
    from aides import drapeau, plafond_total

    table = TableSecurite(
        [drapeau("ylang_ylang", "allergene", statut="brouillon"), plafond_total(6)]
    )
    assert not controler(recette(dose("ylang_ylang", 1)), table=table).conforme


# --- Exclusions personnelles -----------------------------------------------------------------


def test_exclusion_personnelle_ecarte_la_recette() -> None:
    r = recette(dose("lavande_vraie", 2), dose("orange_douce", 2))
    verdict = controler(r, exclusions_perso={"orange_douce": "rougeurs le 2026-09-01"})
    assert not verdict.conforme
    assert any("exclusion personnelle" in m and "rougeurs" in m for m in verdict.rejets)
    assert not controler(r, exclusions_perso={"orange_douce"}).conforme
    with pytest.raises(FicheNonSure):
        assert_fiche_sure(fiche(r), questionnaire(), TABLE, REF, exclusions_perso={"orange_douce"})


# --- Précautions et drapeaux ------------------------------------------------------------


def test_union_des_precautions_et_drapeaux() -> None:
    from agent_he.models import Precaution

    r = recette(
        dose("bergamote", 1),
        dose("lavande_vraie", 2),
        base_volume_ml=25,
        precautions=[Precaution(texte="Tenir hors de portée des enfants", sources=[URL_A])],
    )
    verdict = controler(r)
    assert verdict.conforme, verdict.rejets
    assert verdict.recette is not None
    textes = [p.texte for p in verdict.recette.precautions]
    assert textes[0] == "Tenir hors de portée des enfants"
    assert any("Photosensibilisante" in t for t in textes)
    assert all(p.sources for p in verdict.recette.precautions)
    assert "drapeaux" in verdict.controles


def test_drapeau_non_valide_signale_et_allergie() -> None:
    verdict = controler(recette(dose("tea_tree", 2)), q=questionnaire(allergies=True))
    assert verdict.recette is not None
    assert any("non validée" in p.texte for p in verdict.recette.precautions)
    assert any("test cutané" in a for a in verdict.avertissements)


# --- Contradictions ----------------------------------------------------------------------


def test_contradiction_valeur_la_plus_restrictive() -> None:
    r = recette(dose("lavande_vraie", 6))  # 3 %
    ind = IndicationSource(he_id="lavande_vraie", type="plafond", valeur=2, source=URL_A)
    verdict = controler(r, indications=[ind])
    assert not verdict.conforme
    assert verdict.contradictions
    plus_large = IndicationSource(he_id="lavande_vraie", type="plafond", valeur=10, source=URL_A)
    verdict = controler(r, indications=[plus_large])
    assert verdict.conforme
    assert verdict.contradictions  # divergence signalée même quand la table l'emporte


def test_contre_indication_d_une_source() -> None:
    ind = IndicationSource(
        he_id="lavande_vraie", type="contre_indication", profil="traitement", source=URL_A
    )
    r = recette(dose("lavande_vraie", 2))
    assert controler(r, indications=[ind]).conforme  # profil non concerné
    verdict = controler(r, q=questionnaire(traitement=True), indications=[ind])
    assert not verdict.conforme
    assert verdict.contradictions


# --- Validateur final --------------------------------------------------------------------


def test_synthese_sans_avertissement_refusee() -> None:
    r = recette(dose("lavande_vraie", 2))
    f = fiche(r, mode="synthese")
    assert_fiche_sure(f, questionnaire(), TABLE, REF)
    f.avertissements.remove(AVERTISSEMENT_SYNTHESE)
    with pytest.raises(FicheNonSure):
        assert_fiche_sure(f, questionnaire(), TABLE, REF)


def test_fiche_he_non_tracee_refusee() -> None:
    r = recette(dose("lavande_vraie", 2).model_copy(update={"sources": []}))
    with pytest.raises(FicheNonSure):
        assert_fiche_sure(fiche(r), questionnaire(), TABLE, REF)


def test_fiche_source_non_recuperee_refusee() -> None:
    r = recette(dose("lavande_vraie", 2))
    assert_fiche_sure(fiche(r), questionnaire(), TABLE, REF, sources_recuperees={URL_A})
    with pytest.raises(FicheNonSure):
        assert_fiche_sure(fiche(r), questionnaire(), TABLE, REF, sources_recuperees=set())


def test_fiche_voie_non_demandee_refusee() -> None:
    from agent_he.models import Voie

    r = recette(dose("lavande_vraie", 2))
    with pytest.raises(FicheNonSure):
        assert_fiche_sure(fiche(r), questionnaire(), TABLE, REF, voies_demandees=[Voie.BAIN])


def test_fiche_aucune_acceptee() -> None:
    f = Fiche(mode="aucune", motif="Aucune recette sûre trouvée.", convention_gouttes_ml=20)
    assert_fiche_sure(f, questionnaire(), TABLE, REF)
