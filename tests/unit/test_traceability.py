from agent_he.models import Precaution
from agent_he.safety.traceability import nombre_present, precaution_presente, tracer

from aides import URL_A, URL_B, dose, recette, referentiel

REF = referentiel()
TEXTES = {
    URL_A: "Recette détente : 4 gouttes d'huile essentielle de lavande fine et 2 gouttes "
    "d'orange douce dans 10 ml d'huile végétale. Tenir hors de portée des enfants.",
    URL_B: "Le tea tree (Melaleuca alternifolia) à 1,5 % dans une crème neutre.",
}


def test_recette_entierement_tracee() -> None:
    r = recette(
        dose("lavande_vraie", 4),
        dose("orange_douce", 2),
        dose("tea_tree", 1.5, unite="%", url=URL_B),
        precautions=[Precaution(texte="Tenir hors de portée des enfants", sources=[URL_A])],
    )
    resultat = tracer(r, TEXTES, REF)
    assert resultat.retraits == []
    assert resultat.recette is not None
    assert len(resultat.recette.huiles) == 3
    assert resultat.recette.sources == sorted([URL_A, URL_B])


def test_he_injectee_sans_source_retiree() -> None:
    injectee = dose("cannelle_ecorce", 2).model_copy(update={"sources": []})
    r = recette(dose("lavande_vraie", 4), injectee)
    resultat = tracer(r, TEXTES, REF)
    assert resultat.recette is not None
    assert [h.he_id for h in resultat.recette.huiles] == ["lavande_vraie"]
    assert resultat.huiles_retirees


def test_he_absente_du_texte_cite_retiree() -> None:
    r = recette(dose("lavande_vraie", 4), dose("cannelle_ecorce", 2))
    resultat = tracer(r, TEXTES, REF)
    assert resultat.recette is not None
    assert "cannelle_ecorce" not in {h.he_id for h in resultat.recette.huiles}


def test_dose_absente_du_texte_retiree() -> None:
    resultat = tracer(recette(dose("lavande_vraie", 12)), TEXTES, REF)
    assert resultat.recette is None


def test_source_non_recuperee_retiree() -> None:
    r = recette(dose("lavande_vraie", 4, url="https://inconnu.example/page"))
    assert tracer(r, TEXTES, REF).recette is None


def test_journal_n_est_pas_une_source() -> None:
    r = recette(dose("lavande_vraie", 4, url="journal:usage-42"))
    # Le pipeline ne fournit jamais d'entrée de journal dans `textes` : la dose est retirée.
    assert tracer(r, TEXTES, REF).recette is None


def test_precaution_non_tracee_retiree() -> None:
    r = recette(
        dose("lavande_vraie", 4),
        precautions=[
            Precaution(texte="Peut être ingérée sans risque", sources=[URL_A]),
            Precaution(texte="Tenir hors de portée des enfants", sources=[URL_A]),
        ],
    )
    resultat = tracer(r, TEXTES, REF)
    assert resultat.recette is not None
    assert [p.texte for p in resultat.recette.precautions] == ["Tenir hors de portée des enfants"]
    assert not resultat.huiles_retirees


def test_nombres() -> None:
    assert nombre_present(1.5, "à 1,5 %")
    assert nombre_present(1.5, "1.50 ml")
    assert nombre_present(4, "4 gouttes")
    assert nombre_present(4, "4,0 ml")
    assert not nombre_present(4, "14 gouttes")
    assert not nombre_present(4, "4,5 gouttes")
    assert not nombre_present(1.5, "11,5 %")


def test_precaution_presente() -> None:
    source = "Il ne faut pas appliquer sur les muqueuses."
    assert precaution_presente("Ne pas appliquer sur les muqueuses", source)
    assert precaution_presente(
        "Tenir hors de portée des enfants", "Bien. Tenir hors de portée des enfants !"
    )
    # Une précaution inversée n'est jamais tracée par sa négation.
    assert not precaution_presente("Appliquer sur les muqueuses", source)
    assert not precaution_presente("Peut être ingérée", "Ne pas ingérer.")
    assert not precaution_presente("", "texte")
