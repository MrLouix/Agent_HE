"""Calibrage du seuil de correspondance (spécification §12)."""

from pathlib import Path

import pytest
import yaml

from agent_he.kb.calibrage import SEUILS_PAR_PLONGEUR, calibrer
from agent_he.kb.embeddings import PlongeurLocal, cosinus
from agent_he.pipeline.analyze import categoriser

from scenarios import corpus

PAIRES = yaml.safe_load((Path(__file__).parent / "correspondance.yaml").read_text("utf-8"))


def _scores() -> list[tuple[float, bool]]:
    plongeur = PlongeurLocal()
    recettes = {r.id: r for r in corpus()}
    scores = []
    for paire in PAIRES:
        besoins = categoriser(paire["demande"])
        requete = " ".join([*(str(b) for b in besoins), paire["demande"]])
        a, b = plongeur.plonger([requete, recettes[paire["recette"]].texte_index()])
        scores.append((cosinus(a, b), bool(paire["pertinente"])))
    return scores


def test_seuil_local_separe_les_paires() -> None:
    scores = _scores()
    seuil = SEUILS_PAR_PLONGEUR["local"]
    assert all(s >= seuil for s, p in scores if p), "une paire pertinente serait manquée"
    assert all(s < seuil for s, p in scores if not p), "une paire non pertinente passerait"
    # La valeur par défaut reste proche du calibrage sur le jeu étiqueté.
    assert abs(calibrer(scores) - seuil) <= 0.1


def test_calibrer() -> None:
    assert calibrer([(0.9, True), (0.5, True), (0.4, False), (0.1, False)]) == pytest.approx(0.45)
    assert calibrer([(0.3, True)]) == 0.3
    with pytest.raises(ValueError):
        calibrer([(0.3, False)])
