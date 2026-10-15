import pytest

from agent_he.safety.perimetre import MOTIF_ANIMAUX, MOTIF_INGESTION, hors_perimetre


@pytest.mark.parametrize(
    "texte", ["un mélange pour mon chat stressé", "Chiens anxieux", "pour mon cheval", "my cat"]
)
def test_animaux(texte: str) -> None:
    assert hors_perimetre(texte) == MOTIF_ANIMAUX


@pytest.mark.parametrize(
    "texte",
    [
        "une huile à avaler pour digérer",
        "quelques gouttes dans une tisane",
        "en gélules",
        "par voie interne",
        "sous la langue",
        "une goutte sur une cuillère de miel",
    ],
)
def test_ingestion(texte: str) -> None:
    assert hors_perimetre(texte) == MOTIF_INGESTION


@pytest.mark.parametrize(
    "texte",
    ["mieux dormir", "massage du dos", "diffusion dans la chambre", "achat en ligne", "boutons"],
)
def test_dans_le_perimetre(texte: str) -> None:
    assert hors_perimetre(texte) is None
