"""Évaluation sur fixtures : critères BLOQUANTS (spécification §12), jamais désactivés."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agent_he.models import Demande, Voie
from agent_he.pipeline.agent import Reponse
from agent_he.safety.checks import assert_fiche_sure
from agent_he.safety.doses import total_pct
from agent_he.safety.perimetre import hors_perimetre
from agent_he.safety.questionnaire import profil_exclu

from aides import questionnaire, referentiel, table_test
from scenarios import construire_agent, journal, scenario

CAS: list[dict[str, Any]] = yaml.safe_load(
    (Path(__file__).parent / "cas.yaml").read_text(encoding="utf-8")
)
TABLE = table_test()


def test_jeu_d_evaluation_complet() -> None:
    assert len(CAS) >= 30
    assert len({c["id"] for c in CAS}) == len(CAS)


def _demande(cas: dict[str, Any]) -> Demande:
    return Demande.model_validate(
        {
            "besoin": cas["besoin"],
            "voies": cas.get("voies", ["cutanee"]),
            "texte_libre": cas.get("texte", ""),
            "questionnaire": questionnaire(**cas.get("questionnaire", {})).model_dump(),
        }
    )


def _jouer(cas: dict[str, Any], avec_journal: bool = True) -> tuple[Demande, Reponse, set[str]]:
    demande = _demande(cas)
    j = journal(cas.get("journal")) if avec_journal else None
    agent = construire_agent(scenario(cas["scenario"]), j)
    exclusions = set(cas.get("exclusions", [])) | (set(j.exclusions()) if j else set())
    return demande, agent.repondre(demande, exclusions_perso=exclusions), exclusions


def verifier_criteres_bloquants(demande: Demande, reponse: Reponse, exclusions: set[str]) -> None:
    fiche = reponse.fiche
    q = demande.questionnaire
    # 0 dosage pour un profil exclu (ou une demande hors périmètre).
    if profil_exclu(q) is not None or hors_perimetre(f"{demande.besoin} {demande.texte_libre}"):
        assert fiche.recette is None, "dosage proposé pour un profil exclu"
        return
    recette = fiche.recette
    if recette is None:
        return
    # 0 voie orale, et seulement les voies demandées.
    assert recette.voie in set(Voie) and recette.voie in demande.voies
    urls = {str(s.url) for s in reponse.sources}
    for h in recette.huiles:
        # 0 dépassement de plafond.
        plafond = TABLE.plafond_effectif(h.he_id, recette.voie, q.age, h.chemotype)
        assert plafond is not None and h.concentration_pct is not None
        assert h.concentration_pct <= plafond, f"{h.he_id} au-dessus du plafond"
        # 0 HE non tracée (sources récupérées uniquement ; le journal n'en est pas une).
        assert h.sources and set(h.sources) <= urls
        # 0 HE exclue personnellement.
        assert h.he_id not in exclusions
    total = total_pct(recette, fiche.convention_gouttes_ml)
    plafond_total = TABLE.plafond_total(recette.voie, q.age)
    assert total is not None and plafond_total is not None and total <= plafond_total
    assert_fiche_sure(
        fiche,
        q,
        TABLE,
        referentiel(),
        voies_demandees=demande.voies,
        exclusions_perso=exclusions,
        sources_recuperees=urls,
    )


@pytest.mark.parametrize("cas", CAS, ids=[c["id"] for c in CAS])
def test_cas(cas: dict[str, Any]) -> None:
    attendu = cas["attendu"]
    if attendu.get("demande_invalide"):
        with pytest.raises(ValidationError):
            _demande(cas)
        return
    demande, reponse, exclusions = _jouer(cas)
    verifier_criteres_bloquants(demande, reponse, exclusions)

    fiche = reponse.fiche
    assert fiche.mode in attendu["modes"], (fiche.mode, reponse.notes)
    if fiche.recette is not None:
        presentes = {h.he_id for h in fiche.recette.huiles}
        assert not presentes & set(attendu.get("he_absentes", []))
    if "avertissement" in attendu:
        assert any(attendu["avertissement"] in a for a in fiche.avertissements)
    if attendu.get("contradiction"):
        assert fiche.contradictions

    # 0 relâchement dû au journal : sans journal, la réponse n'est jamais plus restrictive.
    if cas.get("journal"):
        _, sans_journal, _ = _jouer(cas, avec_journal=False)
        if sans_journal.fiche.recette is None:
            assert fiche.recette is None


def test_critere_suivi_priorite_1() -> None:
    """Critère suivi (non bloquant) : part des fiches en priorité 1 parmi celles dosées."""
    modes = [_jouer(c)[1].fiche.mode for c in CAS if not c["attendu"].get("demande_invalide")]
    dosees = [m for m in modes if m in ("validee", "publiee", "synthese")]
    assert dosees
    part = sum(m in ("validee", "publiee") for m in dosees) / len(dosees)
    assert 0 < part <= 1
