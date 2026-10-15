from datetime import date
from pathlib import Path

import pytest

from agent_he.kb.corpus import charger_corpus
from agent_he.kb.validation import ErreurValidation, FileValidation, identifiant_recette
from agent_he.models import Besoin, Confiance
from agent_he.storage.db import connecter

from aides import dose, recette


@pytest.fixture
def file() -> FileValidation:
    return FileValidation(connecter(":memory:"))


def _recette():  # type: ignore[no-untyped-def]
    return recette(dose("lavande_vraie", 6), nom_recette="Roll-on sommeil apaisé")


def test_ajout_sans_doublon(file: FileValidation) -> None:
    a = file.ajouter(_recette(), [Besoin.SOMMEIL], Confiance.COMMERCIAL)
    b = file.ajouter(_recette(), [Besoin.SOMMEIL], Confiance.COMMERCIAL)
    assert a == b
    assert [c.id for c in file.lister()] == [a]
    assert file.obtenir(a).recette == _recette()


def test_validation_exporte_dans_le_corpus(file: FileValidation, tmp_path: Path) -> None:
    cid = file.ajouter(_recette(), [Besoin.SOMMEIL], Confiance.COMMERCIAL)
    rc = file.valider(cid, par="moi", dossier_recettes=tmp_path, le=date(2026, 10, 15))
    assert rc.id == "roll-on-sommeil-apaise"
    assert rc.origine == cid
    assert charger_corpus(tmp_path) == {rc.id: rc}
    assert file.lister() == []
    assert file.obtenir(cid).statut == "validee"
    with pytest.raises(ErreurValidation):
        file.valider(cid, par="moi", dossier_recettes=tmp_path)


def test_validation_identifiant_existant(file: FileValidation, tmp_path: Path) -> None:
    cid = file.ajouter(_recette(), [Besoin.SOMMEIL], Confiance.COMMERCIAL)
    file.valider(cid, par="moi", dossier_recettes=tmp_path)
    autre = recette(dose("lavande_vraie", 4), nom_recette="Roll-on sommeil apaisé")
    cid2 = file.ajouter(autre, [Besoin.SOMMEIL], Confiance.COMMERCIAL)
    with pytest.raises(ErreurValidation):
        file.valider(cid2, par="moi", dossier_recettes=tmp_path)
    assert file.obtenir(cid2).statut == "en_attente"
    rc = file.valider(cid2, par="moi", dossier_recettes=tmp_path, identifiant="roll-on-doux")
    assert rc.id == "roll-on-doux"


def test_rejet(file: FileValidation, tmp_path: Path) -> None:
    cid = file.ajouter(_recette(), [Besoin.SOMMEIL], Confiance.COMMERCIAL)
    with pytest.raises(ErreurValidation):
        file.rejeter(cid, "  ")
    file.rejeter(cid, "dosage douteux")
    assert file.obtenir(cid).motif == "dosage douteux"
    assert file.lister() == []
    assert len(file.lister(None)) == 1
    with pytest.raises(ErreurValidation):
        file.valider(cid, par="moi", dossier_recettes=tmp_path)


def test_candidate_introuvable(file: FileValidation) -> None:
    with pytest.raises(ErreurValidation):
        file.obtenir("C00000000")


def test_identifiant_recette() -> None:
    assert identifiant_recette("Mélange « Été » n°2") == "melange-ete-n-2"
    assert identifiant_recette("!!!") == "recette"


def test_base_persistante(tmp_path: Path) -> None:
    chemin = tmp_path / "sous" / "base.sqlite"
    cid = FileValidation(connecter(chemin)).ajouter(
        _recette(), [Besoin.SOMMEIL], Confiance.COMMERCIAL
    )
    assert FileValidation(connecter(chemin)).obtenir(cid).statut == "en_attente"
