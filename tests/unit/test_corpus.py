import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_he.kb.corpus import charger_corpus, ecrire_recette
from agent_he.kb.embeddings import PlongeurLocal, cosinus
from agent_he.kb.ingest import charger_et_indexer_si_besoin, reindexer
from agent_he.kb.store import ErreurIndex, MagasinChroma, MagasinMemoire
from agent_he.models import Besoin, Voie
from agent_he.pipeline.analyze import categoriser

from aides import DOSSIER_DONNEES, dose, recette, recette_corpus


def test_corpus_du_depot_valide() -> None:
    charger_corpus(DOSSIER_DONNEES / "recettes")


def test_aller_retour(tmp_path: Path) -> None:
    rc = recette_corpus()
    ecrire_recette(tmp_path, rc)
    assert charger_corpus(tmp_path) == {"roll-on-sommeil": rc}
    with pytest.raises(FileExistsError):
        ecrire_recette(tmp_path, rc)


def test_nom_de_fichier_coherent(tmp_path: Path) -> None:
    (tmp_path / "autre.json").write_text(recette_corpus().model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError):
        charger_corpus(tmp_path)


@pytest.mark.parametrize(
    "champ", [{"besoins": []}, {"id": "Avec Espaces"}, {"statut": "brouillon"}]
)
def test_recette_corpus_invalide(champ: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        recette_corpus(**champ)


def test_voie_orale_impossible_dans_le_corpus() -> None:
    donnees = json.loads(recette_corpus().model_dump_json())
    donnees["recette"]["voie"] = "orale"
    with pytest.raises(ValidationError):
        type(recette_corpus()).model_validate(donnees)


# --- Plongements et magasins -----------------------------------------------------------


def test_plongeur_local() -> None:
    p = PlongeurLocal()
    a, b, c = p.plonger(["sommeil apaisant", "Sommeils apaisants", "peau grasse"])
    assert cosinus(a, b) == pytest.approx(1)
    assert cosinus(a, c) == pytest.approx(0)


def _corpus() -> list:  # type: ignore[type-arg]
    peau = recette_corpus(
        id="creme-peau",
        besoins=["peau"],
        mots_cles=["imperfections"],
        recette=recette(dose("tea_tree", 2), nom_recette="Soin peau").model_dump(),
    )
    massage = recette_corpus(
        id="massage-sommeil",
        recette=recette(dose("lavande_vraie", 4), voie="massage").model_dump(),
    )
    return [recette_corpus(), peau, massage]


@pytest.fixture(params=["memoire", "chroma"])
def magasin(request: pytest.FixtureRequest, tmp_path: Path) -> MagasinMemoire | MagasinChroma:
    if request.param == "memoire":
        return MagasinMemoire(PlongeurLocal())
    return MagasinChroma(tmp_path / "chroma", PlongeurLocal())


def test_recherche_filtree(magasin: MagasinMemoire | MagasinChroma) -> None:
    assert magasin.indexer(_corpus()) == 3
    assert magasin.ids() == {"roll-on-sommeil", "creme-peau", "massage-sommeil"}
    resultats = magasin.chercher("sommeil endormissement", [Voie.CUTANEE], [Besoin.SOMMEIL])
    assert [r.id for r in resultats] == ["roll-on-sommeil"]
    assert 0 < resultats[0].similarite <= 1
    deux_voies = magasin.chercher("sommeil", [Voie.CUTANEE, Voie.MASSAGE], [Besoin.SOMMEIL])
    assert {r.id for r in deux_voies} == {"roll-on-sommeil", "massage-sommeil"}
    assert magasin.chercher("sommeil", [Voie.BAIN], [Besoin.SOMMEIL]) == []
    assert magasin.chercher("sommeil", [Voie.CUTANEE], []) == []


def test_reindexation_remplace(magasin: MagasinMemoire | MagasinChroma) -> None:
    magasin.indexer(_corpus())
    magasin.indexer([recette_corpus()])
    assert magasin.ids() == {"roll-on-sommeil"}
    assert magasin.indexer([]) == 0
    assert magasin.chercher("sommeil", [Voie.CUTANEE], [Besoin.SOMMEIL]) == []


def test_chroma_persistant(tmp_path: Path) -> None:
    MagasinChroma(tmp_path, PlongeurLocal()).indexer(_corpus())
    assert len(MagasinChroma(tmp_path, PlongeurLocal()).ids()) == 3


def test_chroma_plongeur_different(tmp_path: Path) -> None:
    MagasinChroma(tmp_path, PlongeurLocal()).indexer(_corpus())
    autre = PlongeurLocal(dimension=64)
    autre.nom = "autre"
    with pytest.raises(ErreurIndex):
        MagasinChroma(tmp_path, autre).chercher("sommeil", [Voie.CUTANEE], [Besoin.SOMMEIL])


def test_ingestion(tmp_path: Path) -> None:
    for rc in _corpus():
        ecrire_recette(tmp_path, rc)
    magasin = MagasinMemoire(PlongeurLocal())
    assert len(reindexer(tmp_path, magasin)) == 3
    assert len(charger_et_indexer_si_besoin(tmp_path, magasin)) == 3
    (tmp_path / "creme-peau.json").unlink()
    charger_et_indexer_si_besoin(tmp_path, magasin)
    assert magasin.ids() == {"roll-on-sommeil", "massage-sommeil"}


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        ("mélange pour mieux dormir", [Besoin.SOMMEIL]),
        ("stress et insomnie", [Besoin.SOMMEIL, Besoin.STRESS]),
        ("boutons d'acné", [Besoin.PEAU]),
        ("douleurs musculaires après le sport", [Besoin.DOULEURS]),
        ("assainir l'air de la maison", [Besoin.AMBIANCE]),
        ("bonjour", []),
    ],
)
def test_categoriser(texte: str, attendu: list[Besoin]) -> None:
    assert categoriser(texte) == attendu
