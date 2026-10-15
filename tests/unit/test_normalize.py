import pytest

from agent_he.models import Voie
from agent_he.pipeline.extract import IndicationBrute, RecetteBrute
from agent_he.pipeline.normalize import (
    normaliser_indication,
    normaliser_recette,
    normaliser_unite,
    normaliser_voie,
)

from aides import referentiel
from web import URL_SOMMEIL, recette_sommeil

REF = referentiel()
URLS = {URL_SOMMEIL}


def brute(**surcharges: object) -> RecetteBrute:
    return RecetteBrute.model_validate({**recette_sommeil(), **surcharges})


def test_recette_normalisee() -> None:
    norm = normaliser_recette(brute(), REF, URLS)
    assert norm.recette is not None
    assert norm.notes == []
    assert [h.he_id for h in norm.recette.huiles] == ["lavande_vraie", "orange_douce"]
    assert norm.recette.voie == Voie.CUTANEE
    assert norm.recette.huiles[0].nom == "Lavande vraie"
    assert norm.recette.sources == [URL_SOMMEIL]
    assert not norm.huiles_exclues


@pytest.mark.parametrize("voie", ["orale", "voie orale", "ingestion", "sublinguale", ""])
def test_voie_orale_ou_inconnue_rejetee(voie: str) -> None:
    norm = normaliser_recette(brute(voie=voie), REF, URLS)
    assert norm.recette is None


@pytest.mark.parametrize(
    ("texte", "voie"),
    [("Diffusion", Voie.DIFFUSION), ("application cutanée", Voie.CUTANEE), ("Bain", Voie.BAIN)],
)
def test_voies(texte: str, voie: Voie) -> None:
    assert normaliser_voie(texte) == voie


@pytest.mark.parametrize(
    ("texte", "unite"), [("gouttes", "gouttes"), ("Gtt", "gouttes"), ("mL", "ml"), ("%", "%")]
)
def test_unites(texte: str, unite: str) -> None:
    assert normaliser_unite(texte) == unite


def test_he_non_reconnue_exclue() -> None:
    donnees = recette_sommeil()
    donnees["huiles"][1]["nom"] = "huile de licorne"
    donnees["huiles"][1]["nom_latin"] = "Unicornus magicus"
    norm = normaliser_recette(RecetteBrute.model_validate(donnees), REF, URLS)
    assert norm.recette is not None
    assert [h.he_id for h in norm.recette.huiles] == ["lavande_vraie"]
    assert any("licorne" in n for n in norm.notes)
    assert norm.huiles_exclues


def test_url_non_recuperee_ignoree() -> None:
    norm = normaliser_recette(brute(), REF, set())
    assert norm.recette is None


def test_unite_inconnue_exclue() -> None:
    donnees = recette_sommeil()
    donnees["huiles"][0]["quantite"]["unite"] = "cuillères"
    norm = normaliser_recette(RecetteBrute.model_validate(donnees), REF, URLS)
    assert norm.recette is not None
    assert [h.he_id for h in norm.recette.huiles] == ["orange_douce"]


def test_chemotype_inconnu_ignore() -> None:
    donnees = recette_sommeil()
    donnees["huiles"][0]["chemotype"] = "linalol"
    donnees["huiles"][1]["chemotype"] = "nimporte"
    norm = normaliser_recette(RecetteBrute.model_validate(donnees), REF, URLS)
    assert norm.recette is not None
    assert norm.recette.huiles[0].chemotype == "linalol"
    # Un chémotype qui ne correspond pas au référentiel rend le nom ambigu ⇒ exclusion.
    assert len(norm.recette.huiles) == 1


def test_indications() -> None:
    plafond = IndicationBrute(
        nom="lavande vraie", type="plafond", valeur=3, unite="%", voie="cutanée", source=URL_SOMMEIL
    )
    ind = normaliser_indication(plafond, REF, URLS)
    assert ind is not None
    assert (ind.he_id, ind.valeur, ind.voie) == ("lavande_vraie", 3, Voie.CUTANEE)
    contre = IndicationBrute(
        nom="lavande vraie", type="contre_indication", profil="femme enceinte", source=URL_SOMMEIL
    )
    ind = normaliser_indication(contre, REF, URLS)
    assert ind is not None
    assert ind.profil == "grossesse_allaitement"
    gouttes = plafond.model_copy(update={"unite": "gouttes"})
    assert normaliser_indication(gouttes, REF, URLS) is None
    assert normaliser_indication(plafond, REF, set()) is None
