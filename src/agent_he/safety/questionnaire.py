"""Questionnaire de sécurité ⇒ refus ou exclusions d'HE (spécification §8)."""

from dataclasses import dataclass, field

from agent_he.models import Drapeau, Questionnaire, TrancheAge
from agent_he.referentiel.securite import Profil, ProfilRisque, TableSecurite

RENVOI_PROFESSIONNEL = (
    "Demande conseil à un professionnel de santé (médecin, sage-femme ou pharmacien) "
    "avant tout usage d'huiles essentielles."
)

_AGES_REFUSES = {
    TrancheAge.MOINS_3: "Enfant de moins de 3 ans",
    TrancheAge.DE_3_A_6: "Enfant de 3 à 6 ans",
}
_PROFILS_REFUSES = {
    ProfilRisque.GROSSESSE_ALLAITEMENT: "Grossesse ou allaitement",
    ProfilRisque.EPILEPSIE: "Épilepsie",
    ProfilRisque.ASTHME: "Asthme",
}


@dataclass(frozen=True)
class Motif:
    """Raison d'un refus de dosage."""

    texte: str
    profils: tuple[Profil, ...] = field(default_factory=tuple)


def profils_actifs(q: Questionnaire) -> set[Profil]:
    """Profils de risque cochés, plus la tranche d'âge."""
    actifs: set[Profil] = {q.age}
    if q.grossesse_allaitement:
        actifs.add(ProfilRisque.GROSSESSE_ALLAITEMENT)
    if q.epilepsie:
        actifs.add(ProfilRisque.EPILEPSIE)
    if q.asthme:
        actifs.add(ProfilRisque.ASTHME)
    if q.traitement:
        actifs.add(ProfilRisque.TRAITEMENT)
    if q.pathologie_hormonale:
        actifs.add(ProfilRisque.PATHOLOGIE_HORMONALE)
    return actifs


def profil_exclu(q: Questionnaire) -> Motif | None:
    """Motif de refus de tout dosage, ou `None` si le profil autorise une recherche."""
    raisons: list[str] = []
    profils: list[Profil] = []
    if q.age in _AGES_REFUSES:
        raisons.append(_AGES_REFUSES[q.age])
        profils.append(q.age)
    actifs = profils_actifs(q)
    for profil, libelle in _PROFILS_REFUSES.items():
        if profil in actifs:
            raisons.append(libelle)
            profils.append(profil)
    if not raisons:
        return None
    texte = (
        f"{', '.join(raisons)} : l'outil ne propose aucun dosage pour ce profil. "
        f"{RENVOI_PROFESSIONNEL}"
    )
    return Motif(texte=texte, profils=tuple(profils))


def he_exclues(q: Questionnaire, table: TableSecurite) -> dict[str, str]:
    """HE interdites pour ce profil, avec leur motif (`he_id` ⇒ motif)."""
    exclues: dict[str, str] = {}
    for profil in profils_actifs(q):
        for he_id in table.he_interdites(profil):
            exclues.setdefault(he_id, f"contre-indiquée pour le profil « {profil} »")
    if q.traitement:
        for he_id in table.he_avec_drapeau(Drapeau.INTERACTION_MEDICAMENT):
            exclues.setdefault(he_id, "interaction médicamenteuse possible (traitement en cours)")
    if q.pathologie_hormonale:
        for he_id in table.he_avec_drapeau(Drapeau.HORMONE_LIKE):
            exclues.setdefault(he_id, "effet hormone-like (pathologie hormonodépendante)")
    return exclues


def he_a_eviter(q: Questionnaire, table: TableSecurite) -> list[str]:
    """HE à éviter, listées dans un refus explicatif (issues de la table de sécurité)."""
    return sorted(he_exclues(q, table))


def avertissements_profil(q: Questionnaire) -> list[str]:
    messages: list[str] = []
    if q.traitement:
        messages.append(
            "Traitement en cours : les HE à risque d'interaction ont été exclues ; "
            "vérifie l'absence d'interaction avec ton pharmacien."
        )
    if q.allergies:
        messages.append(
            "Allergies ou peau sensible : fais un test cutané (une goutte du mélange dilué "
            "au pli du coude, attendre 24 h) avant usage."
        )
    if q.age == TrancheAge.PLUS_65:
        messages.append("Plus de 65 ans : plafonds réduits appliqués lorsque la table les prévoit.")
    return messages
