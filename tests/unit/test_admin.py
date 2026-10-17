"""Administration des fichiers boutiques.yaml et securite.yaml (sans Streamlit)."""

import shutil
from datetime import date
from pathlib import Path

import pytest

from agent_he.admin import (
    ErreurAdmin,
    enregistrer_entree,
    lire_boutiques,
    lire_securite,
    modifier_boutique,
    prochain_id,
    remplacer_entree,
    retirer,
)
from agent_he.referentiel.securite import (
    ErreurCycle,
    Statut,
    ecrire_entrees,
    empreinte,
    etat_effectif,
)

from aides import DOSSIER_DONNEES, entree

SAISIE = {
    "type": "drapeau",
    "he_id": "bergamote",
    "nom_latin": "Citrus bergamia",
    "drapeau": "phototoxique",
    "source": {
        "ouvrage": "Ouvrage fictif de test",
        "page": 1,
        "localisation": "test",
        "citation": "citation fictive de test",
    },
    "saisie": {"par": "testeur", "le": "2026-01-01", "methode": "manuelle"},
}


@pytest.fixture
def dossier(tmp_path: Path) -> Path:
    for nom in ("boutiques.yaml", "huiles.yaml"):
        shutil.copy(DOSSIER_DONNEES / nom, tmp_path / nom)
    ecrire_entrees(
        tmp_path / "securite.yaml",
        [entree(statut="valide", id="SEC-0001"), entree(statut="brouillon", id="SEC-0002")],
        entete="# Table de test\n",
    )
    return tmp_path


# --- Boutiques -----------------------------------------------------------------------


def test_modifier_boutique_conserve_entete_et_autres_champs(dossier: Path) -> None:
    avant = (dossier / "boutiques.yaml").read_text(encoding="utf-8")
    modifier_boutique(
        dossier,
        "aroma-zone",
        {
            "url_cgu": "https://www.aroma-zone.com/cgv",
            "cgu_verifiees": True,
            "cgu_verifiees_le": date(2026, 10, 18),
            "url_recherche": "https://www.aroma-zone.com/recherche?q={q}",
            "motif_lien_produit": r"/info/fiche-technique/[\w-]+",
        },
    )
    apres = (dossier / "boutiques.yaml").read_text(encoding="utf-8")
    assert apres.startswith(avant.split("\n- id:")[0].rstrip())
    assert "url: https://www.aroma-zone.com\n" in apres  # écrite à l'identique
    boutique = next(b for b in lire_boutiques(dossier) if b.id == "aroma-zone")
    assert boutique.active
    assert boutique.cgu_verifiees_le == date(2026, 10, 18)
    assert not next(b for b in lire_boutiques(dossier) if b.id == "puressentiel").active


def test_boutique_champs_en_lecture_seule_refuses(dossier: Path) -> None:
    with pytest.raises(ErreurAdmin, match="lecture seule"):
        modifier_boutique(dossier, "aroma-zone", {"url": "https://ailleurs.example"})


def test_boutique_invalide_non_ecrite(dossier: Path) -> None:
    avant = (dossier / "boutiques.yaml").read_text(encoding="utf-8")
    with pytest.raises(ErreurAdmin, match=r"\{q\}"):
        modifier_boutique(dossier, "aroma-zone", {"url_recherche": "https://x.example/r"})
    with pytest.raises(ErreurAdmin, match="introuvable"):
        modifier_boutique(dossier, "inconnue", {"delai_s": 3})
    assert (dossier / "boutiques.yaml").read_text(encoding="utf-8") == avant


def test_cgu_non_verifiees_efface_la_date(dossier: Path) -> None:
    modifier_boutique(
        dossier, "aroma-zone", {"cgu_verifiees": True, "cgu_verifiees_le": date(2026, 1, 1)}
    )
    modifier_boutique(dossier, "aroma-zone", {"cgu_verifiees": False})
    boutique = next(b for b in lire_boutiques(dossier) if b.id == "aroma-zone")
    assert boutique.cgu_verifiees_le is None


# --- Table de sécurité ---------------------------------------------------------------


def test_creation_attribue_l_identifiant_suivant(dossier: Path) -> None:
    creee = enregistrer_entree(dossier, {**SAISIE, "statut": "valide"})
    assert creee.id == "SEC-0003"
    assert creee.statut == Statut.BROUILLON  # les champs de suivi ne se saisissent pas
    assert (dossier / "securite.yaml").read_text(encoding="utf-8").startswith("# Table de test")
    assert prochain_id(lire_securite(dossier)) == "SEC-0004"


def test_creation_invalide_refusee(dossier: Path) -> None:
    with pytest.raises(ErreurAdmin, match="drapeau"):
        enregistrer_entree(dossier, {**SAISIE, "drapeau": None})
    assert len(lire_securite(dossier)) == 2


def test_modifier_champ_de_fond_ramene_en_brouillon(dossier: Path) -> None:
    validee = next(e for e in lire_securite(dossier) if e.id == "SEC-0001")
    donnees = validee.model_dump(mode="json")
    enregistrer_entree(dossier, donnees)  # aucun changement : reste validée
    assert next(e for e in lire_securite(dossier) if e.id == "SEC-0001").statut == Statut.VALIDE

    donnees["valeur"] = 1
    modifiee = enregistrer_entree(dossier, donnees)
    assert modifiee.statut == Statut.BROUILLON
    assert modifiee.validation.empreinte is None
    assert not etat_effectif(modifiee).applique
    assert modifiee.verification.empreinte != empreinte(modifiee)


def test_retrait_obligatoirement_motive_puis_fige(dossier: Path) -> None:
    e = next(e for e in lire_securite(dossier) if e.id == "SEC-0002")
    with pytest.raises(ErreurCycle, match="motif"):
        retirer(e, "  ")
    remplacer_entree(dossier, retirer(e, "erreur de page", date(2026, 10, 18)))
    retiree = next(e for e in lire_securite(dossier) if e.id == "SEC-0002")
    assert retiree.statut == Statut.RETIRE
    assert retiree.motif_retrait == "erreur de page (2026-10-18)"
    with pytest.raises(ErreurAdmin, match="retirée"):
        enregistrer_entree(dossier, retiree.model_dump(mode="json"))
    assert prochain_id(lire_securite(dossier)) == "SEC-0003"
