import pytest

from agent_he.referentiel.huiles import Huile, Referentiel, simplifier

from aides import referentiel

REF = referentiel()


def test_referentiel_couvre_une_trentaine_d_he() -> None:
    assert len(REF) >= 30


def test_acceptation_lavande() -> None:
    attendu = "lavande_vraie"
    assert REF.normaliser("lavande fine") == attendu
    assert REF.normaliser("True lavender") == attendu
    assert REF.normaliser("Lavandula angustifolia") == attendu


@pytest.mark.parametrize(
    ("nom", "attendu"),
    [
        ("Lavande Vraie", "lavande_vraie"),
        ("LAVANDULA  ANGUSTIFOLIA", "lavande_vraie"),
        ("Huile essentielle de lavande fine", "lavande_vraie"),
        ("HE d'arbre à thé", "tea_tree"),
        ("Tea tree essential oil", "tea_tree"),
        ("Mentha × piperita", "menthe_poivree"),
        ("Mentha x piperita", "menthe_poivree"),
        ("Mentha piperita", "menthe_poivree"),
        ("Géranium rosat", "geranium_rosat"),
        ("geranium rosat", "geranium_rosat"),
        ("Néroli", "neroli"),
        ("lavande_vraie", "lavande_vraie"),
        ("Salvia rosmarinus ct camphre", "romarin_camphre"),
        ("Thymus vulgaris CT thymol", "thym_thymol"),
        ("Thymus vulgaris chémotype linalol", "thym_linalol"),
    ],
)
def test_normaliser(nom: str, attendu: str) -> None:
    assert REF.normaliser(nom) == attendu


@pytest.mark.parametrize("nom", ["Thymus vulgaris", "Rosmarinus officinalis", "Citrus aurantium"])
def test_nom_ambigu_sans_chemotype(nom: str) -> None:
    assert REF.normaliser(nom) is None
    assert len(REF.candidats(nom)) > 1


def test_chemotype_leve_l_ambiguite() -> None:
    assert REF.normaliser("Thymus vulgaris", chemotype="thymol") == "thym_thymol"
    assert REF.normaliser("Rosmarinus officinalis", chemotype="1,8-cinéole") == "romarin_cineole"


def test_chemotype_incompatible() -> None:
    assert REF.normaliser("Lavande vraie", chemotype="thymol") is None
    assert REF.normaliser("Lavande vraie", chemotype="linalol") == "lavande_vraie"


@pytest.mark.parametrize("nom", ["", "huile de licorne", "Lavandula", "cannelle de chine"])
def test_nom_inconnu(nom: str) -> None:
    assert REF.normaliser(nom) is None


def test_nom_latin_et_chemotype_distincts() -> None:
    for huile in REF:
        latins = {simplifier(n) for n in huile.noms_latins()}
        assert not latins & {simplifier(c) for c in huile.chemotypes}


def test_latin_coherent() -> None:
    assert REF.latin_coherent("lavande_vraie", "Lavandula officinalis")
    assert not REF.latin_coherent("lavande_vraie", "Lavandula latifolia")
    assert not REF.latin_coherent("inconnue", "Lavandula angustifolia")


def test_identifiant_en_double_refuse() -> None:
    huile = Huile(id="x", nom_latin="X x", noms_fr=["X"])
    with pytest.raises(ValueError):
        Referentiel([huile, huile])


def test_noms_sans_collision_imprevue() -> None:
    """Un nom usuel (FR/EN) ne doit désigner qu'une seule HE."""
    for huile in REF:
        for nom in [*huile.noms_fr, *huile.noms_en]:
            assert REF.candidats(nom) == {huile.id}, nom
