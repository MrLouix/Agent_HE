"""Orchestrateur de l'agent (spécification §5, §6).

Ordre : contrôle de sécurité initial (avant toute recherche) ⇒ recherche web (liste
blanche, puis passage ouvert optionnel) ⇒ récupération ⇒ extraction (LLM) ⇒
normalisation ⇒ traçabilité ⇒ contrôles communs ⇒ fiche validée par `assert_fiche_sure`.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from agent_he.kb.corpus import RecetteCorpus
from agent_he.kb.store import Magasin
from agent_he.kb.validation import FileValidation
from agent_he.llm.base import LLM, ErreurLLM
from agent_he.models import Besoin, Confiance, Demande, Fiche, Recette, Source
from agent_he.pipeline.analyze import categoriser
from agent_he.pipeline.extract import extraire
from agent_he.pipeline.normalize import normaliser_indication, normaliser_recette
from agent_he.referentiel.huiles import Referentiel
from agent_he.referentiel.securite import TableSecurite
from agent_he.safety.checks import IndicationSource, assert_fiche_sure, controler_recette
from agent_he.safety.questionnaire import avertissements_profil, he_a_eviter, profil_exclu
from agent_he.safety.traceability import tracer
from agent_he.search.base import ErreurRecherche, Page, Recherche, Recuperateur
from agent_he.search.fetch import contient_injection
from agent_he.search.reliability import BADGES, Fiabilite


@dataclass
class Reglages:
    convention_gouttes_ml: int = 20
    recherche_ouverte: bool = False
    max_resultats: int = 5
    seuil_correspondance: float = 0.8


@dataclass
class Reponse:
    fiche: Fiche
    sources: list[Source] = field(default_factory=list)
    controles: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    """Déroulé lisible (pages écartées, HE exclues, rejets) pour l'utilisateur et l'audit."""


@dataclass
class Candidate:
    """Recette conforme, prête à être présentée."""

    recette: Recette
    mode: str
    contradictions: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    controles: list[str] = field(default_factory=list)


class Agent:
    def __init__(
        self,
        *,
        llm: LLM,
        recherche: Recherche,
        recuperateur: Recuperateur,
        table: TableSecurite,
        referentiel: Referentiel,
        fiabilite: Fiabilite,
        reglages: Reglages | None = None,
        magasin: Magasin | None = None,
        corpus: Mapping[str, RecetteCorpus] | None = None,
        file_validation: FileValidation | None = None,
    ) -> None:
        self.llm = llm
        self.recherche = recherche
        self.recuperateur = recuperateur
        self.table = table
        self.referentiel = referentiel
        self.fiabilite = fiabilite
        self.reglages = reglages or Reglages()
        self.magasin = magasin
        self.corpus: Mapping[str, RecetteCorpus] = corpus or {}
        self.file_validation = file_validation

    # --- Étapes ---------------------------------------------------------------------

    def refus(self, demande: Demande) -> Reponse | None:
        """Contrôle de sécurité initial : refus explicatif pour un profil exclu."""
        motif = profil_exclu(demande.questionnaire)
        if motif is None:
            return None
        fiche = Fiche(
            mode="refus",
            motif=motif.texte,
            he_a_eviter=he_a_eviter(demande.questionnaire, self.table),
            convention_gouttes_ml=self.reglages.convention_gouttes_ml,
        )
        return Reponse(fiche=fiche, controles=["profil_exclu"])

    def requete(self, demande: Demande) -> str:
        voies = ", ".join(demande.voies)
        return f"recette huiles essentielles {demande.besoin} {voies}"

    def recuperer_pages(self, demande: Demande, notes: list[str]) -> list[Page]:
        requete = self.requete(demande)
        resultats = self.recherche.rechercher(
            requete, self.fiabilite.liste_blanche(), self.reglages.max_resultats
        )
        if self.reglages.recherche_ouverte:
            resultats += self.recherche.rechercher(requete, None, self.reglages.max_resultats)
        pages: list[Page] = []
        vues: set[str] = set()
        for resultat in resultats:
            if resultat.url in vues:
                continue
            vues.add(resultat.url)
            try:
                page = self.recuperateur.recuperer(resultat.url)
            except ErreurRecherche as exc:
                notes.append(str(exc))
                continue
            if contient_injection(page.texte):
                notes.append(f"Page écartée (consignes adressées à une IA) : {page.url}")
                continue
            if page.texte.strip():
                pages.append(page)
        return pages

    def source(self, page: Page) -> Source:
        return Source.model_validate(
            {
                "url": page.url,
                "titre": page.titre,
                "confiance": self.fiabilite.confiance(page.url),
                "extrait": page.texte[:300],
            }
        )

    def besoins(self, demande: Demande) -> list[Besoin]:
        return categoriser(f"{demande.besoin} {demande.texte_libre}")

    def source_url(self, url: str) -> Source:
        return Source.model_validate(
            {"url": url, "titre": url, "confiance": self.fiabilite.confiance(url)}
        )

    def candidates_corpus(
        self,
        demande: Demande,
        besoins: list[Besoin],
        exclusions_perso: Mapping[str, str] | Collection[str],
        notes: list[str],
        controles: list[str],
    ) -> list[Candidate]:
        """Priorité 1a : recettes validées proches du besoin et conformes."""
        if self.magasin is None or not besoins:
            return []
        candidates: list[Candidate] = []
        texte = f"{' '.join(besoins)} {demande.besoin}"
        for correspondance in self.magasin.chercher(texte, demande.voies, besoins):
            entree = self.corpus.get(correspondance.id)
            if entree is None or correspondance.similarite < self.reglages.seuil_correspondance:
                continue
            verdict = controler_recette(
                entree.recette,
                demande.questionnaire,
                self.table,
                self.referentiel,
                convention_gouttes_ml=self.reglages.convention_gouttes_ml,
                exclusions_perso=exclusions_perso,
            )
            controles.extend(verdict.controles)
            if not verdict.conforme or verdict.recette is None:
                notes.extend(
                    f"« {entree.recette.nom_recette} » écartée : {r}" for r in verdict.rejets
                )
                continue
            candidates.append(
                Candidate(
                    recette=verdict.recette,
                    mode="validee",
                    avertissements=verdict.avertissements,
                    controles=verdict.controles,
                )
            )
        return candidates

    def candidates_web(
        self,
        demande: Demande,
        pages: list[Page],
        exclusions_perso: Mapping[str, str] | Collection[str],
        notes: list[str],
        controles: list[str],
    ) -> tuple[list[Candidate], list[IndicationSource], list[str]]:
        """Recettes publiées conformes (priorité 1b), indications et contradictions relevées."""
        if not pages:
            return [], [], []
        textes = {p.url: p.texte for p in pages}
        extraction = extraire(self.llm, demande.besoin, [str(v) for v in demande.voies], pages)
        indications = [
            i
            for brute in extraction.indications
            if (i := normaliser_indication(brute, self.referentiel, textes)) is not None
        ]
        candidates: list[Candidate] = []
        for brute in extraction.recettes:
            norm = normaliser_recette(brute, self.referentiel, textes)
            notes.extend(norm.notes)
            if norm.recette is None or norm.recette.voie not in demande.voies:
                continue
            if norm.huiles_exclues:
                # Une recette verbatim amputée d'une HE n'est plus la recette publiée.
                notes.append(f"« {brute.nom_recette} » écartée : HE non retenue(s)")
                controles.append("normalisation")
                continue
            trace = tracer(norm.recette, textes, self.referentiel)
            notes.extend(trace.retraits)
            if trace.recette is None or trace.huiles_retirees:
                # Une recette verbatim amputée d'une HE n'est plus la recette publiée.
                controles.append("tracabilite")
                continue
            verdict = controler_recette(
                trace.recette,
                demande.questionnaire,
                self.table,
                self.referentiel,
                convention_gouttes_ml=self.reglages.convention_gouttes_ml,
                exclusions_perso=exclusions_perso,
                indications=indications,
            )
            controles.extend(verdict.controles)
            if not verdict.conforme or verdict.recette is None:
                notes.extend(f"« {brute.nom_recette} » rejetée : {r}" for r in verdict.rejets)
                continue
            candidates.append(
                Candidate(
                    recette=verdict.recette,
                    mode="publiee",
                    contradictions=verdict.contradictions,
                    avertissements=verdict.avertissements,
                    controles=verdict.controles,
                )
            )
        return candidates, indications, extraction.contradictions

    def fiche(self, demande: Demande, candidate: Candidate, sources: list[Source]) -> Fiche:
        sites = sorted({s.domaine for s in sources if str(s.url) in candidate.recette.sources})
        badges: list[str] = []
        if candidate.mode == "validee":
            badges.append(f"✅ Recette validée — source : {', '.join(sites)}")
        elif candidate.mode == "publiee":
            badges.append(f"📄 Recette publiée — source : {', '.join(sites)} (non relue)")
        for s in sources:
            if str(s.url) in candidate.recette.sources:
                badges.append(f"{BADGES[s.confiance]} — {s.domaine}")
        avertissements = [*avertissements_profil(demande.questionnaire), *candidate.avertissements]
        return Fiche.model_validate(
            {
                "mode": candidate.mode,
                "recette": candidate.recette.model_dump(),
                "badges": badges,
                "avertissements": avertissements,
                "contradictions": candidate.contradictions,
                "convention_gouttes_ml": self.reglages.convention_gouttes_ml,
            }
        )

    @staticmethod
    def motif_aucune(notes: list[str]) -> str:
        motif = "Aucune recette sûre trouvée dans les sources consultées."
        rejets = [n for n in notes if "rejetée" in n or "écartée" in n]
        if rejets:
            motif += " Motifs : " + " ; ".join(rejets[:5])
        return motif

    def aucune(self, motif: str) -> Fiche:
        return Fiche(
            mode="aucune", motif=motif, convention_gouttes_ml=self.reglages.convention_gouttes_ml
        )

    # --- Point d'entrée ---------------------------------------------------------------

    def repondre(
        self,
        demande: Demande,
        exclusions_perso: Mapping[str, str] | Collection[str] = (),
    ) -> Reponse:
        refus = self.refus(demande)
        if refus is not None:
            return refus

        notes: list[str] = []
        controles: list[str] = []
        besoins = self.besoins(demande)

        corpus = self.candidates_corpus(demande, besoins, exclusions_perso, notes, controles)
        if corpus:
            sources = [self.source_url(u) for u in corpus[0].recette.sources]
            return self.finaliser(
                demande, corpus[0], sources, [], exclusions_perso, controles, notes
            )

        try:
            pages = self.recuperer_pages(demande, notes)
            candidates, _, contradictions = self.candidates_web(
                demande, pages, exclusions_perso, notes, controles
            )
        except (ErreurRecherche, ErreurLLM) as exc:
            motif = f"Recherche impossible : {exc}"
            return Reponse(fiche=self.aucune(motif), controles=controles, notes=notes)
        sources = [self.source(p) for p in pages]
        if not candidates:
            return Reponse(self.aucune(self.motif_aucune(notes)), sources, controles, notes)

        choisie = candidates[0]
        if self.file_validation is not None:
            confiance = min(
                (s.confiance for s in sources if str(s.url) in choisie.recette.sources),
                key=list(Confiance).index,
                default=Confiance.NON_VERIFIE,
            )
            cid = self.file_validation.ajouter(choisie.recette, besoins, confiance)
            notes.append(f"Recette ajoutée à la file de validation ({cid})")
        return self.finaliser(
            demande, choisie, sources, contradictions, exclusions_perso, controles, notes
        )

    def finaliser(
        self,
        demande: Demande,
        candidate: Candidate,
        sources: list[Source],
        contradictions: list[str],
        exclusions_perso: Mapping[str, str] | Collection[str],
        controles: list[str],
        notes: list[str],
    ) -> Reponse:
        """Construit la fiche et la soumet au validateur final (dernier rempart)."""
        fiche = self.fiche(demande, candidate, sources)
        fiche.contradictions.extend(contradictions)
        assert_fiche_sure(
            fiche,
            demande.questionnaire,
            self.table,
            self.referentiel,
            voies_demandees=demande.voies,
            exclusions_perso=set(exclusions_perso),
            sources_recuperees={str(s.url) for s in sources},
        )
        utilisees = [s for s in sources if str(s.url) in candidate.recette.sources]
        return Reponse(fiche, utilisees, controles, notes)
