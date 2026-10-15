import pytest

from agent_he.models import Quantite
from agent_he.safety.doses import (
    affichage,
    avec_concentrations,
    concentration_pct,
    mettre_a_echelle,
    total_pct,
    volume_ml,
)

from aides import dose, recette


def q(valeur: float, unite: str) -> Quantite:
    return Quantite(valeur=valeur, unite=unite)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("quantite", "base", "convention", "attendu"),
    [
        (q(20, "gouttes"), 10, 20, 10.0),  # 1 ml dans 10 ml
        (q(3, "gouttes"), 10, 20, 1.5),
        (q(3, "gouttes"), 10, 40, 0.75),
        (q(0.5, "ml"), 50, 20, 1.0),
        (q(2, "%"), None, 20, 2.0),
        (q(2, "%"), 30, 20, 2.0),
    ],
)
def test_concentration(
    quantite: Quantite, base: float | None, convention: int, attendu: float
) -> None:
    assert concentration_pct(quantite, base, convention) == pytest.approx(attendu)


def test_concentration_non_calculable_sans_base() -> None:
    assert concentration_pct(q(3, "gouttes"), None, 20) is None
    assert concentration_pct(q(1, "ml"), None, 20) is None


def test_volume() -> None:
    assert volume_ml(q(10, "gouttes"), 20, None) == pytest.approx(0.5)
    assert volume_ml(q(2, "%"), 20, 50) == pytest.approx(1)
    assert volume_ml(q(2, "%"), 20, None) is None


def test_affichage() -> None:
    a = affichage(dose("lavande_vraie", 6), base_volume_ml=10, convention_gouttes_ml=20)
    assert a.pourcentage == pytest.approx(3)
    assert a.ml == pytest.approx(0.3)
    assert a.gouttes == pytest.approx(6)


def test_avec_concentrations_et_total() -> None:
    r = recette(dose("lavande_vraie", 4), dose("orange_douce", 2), base_volume_ml=10)
    calculee = avec_concentrations(r, 20)
    assert [h.concentration_pct for h in calculee.huiles] == [2, 1]
    assert total_pct(r, 20) == pytest.approx(3)
    assert total_pct(recette(dose("lavande_vraie", 4), base_volume_ml=None), 20) is None


def test_mise_a_echelle_conserve_la_concentration() -> None:
    r = recette(dose("lavande_vraie", 6), dose("orange_douce", 1, unite="%"), base_volume_ml=10)
    grande = mettre_a_echelle(r, 50, 20)
    assert grande.base_volume_ml == 50
    assert grande.huiles[0].quantite == q(1.5, "ml")
    assert [h.concentration_pct for h in grande.huiles] == pytest.approx([3, 1])
    assert concentration_pct(grande.huiles[0].quantite, 50, 20) == pytest.approx(3)


def test_mise_a_echelle_impossible() -> None:
    with pytest.raises(ValueError):
        mettre_a_echelle(recette(dose("lavande_vraie", 6), base_volume_ml=None), 50, 20)
    with pytest.raises(ValueError):
        mettre_a_echelle(recette(dose("lavande_vraie", 6)), 0, 20)
