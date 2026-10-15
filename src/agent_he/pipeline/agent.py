"""Orchestrateur de l'agent : arbre de décision de la spécification §6.

contrôle de sécurité initial (avant toute recherche) ⇒ analyse ⇒ plan ⇒
1a corpus validé ⇒ 1b recette publiée (web) ⇒ 2 synthèse tracée ⇒ aucune recette sûre.
Chaque recette passe les contrôles communs ; chaque fiche passe `assert_fiche_sure` ;
chaque réponse laisse une entrée dans le journal d'audit.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from agent_he.journal.ranking import classer
from agent_he.journal.repository import Journal
from agent_he.journal.stats import rappel, stats_recette
from agent_he.kb.corpus import RecetteCorpus
from agent_he.kb.store import ErreurIndex, Magasin
from agent_he.kb.validation import FileValidation
from agent_he.llm.base import LLM, ErreurLLM
from agent_he.models import (
    Confiance,
    Demande,
    EntreeAudit,
    Fiche,
    Recette,
    Source,
    Tolerance,
    Voie,
)
from agent_he.pipeline.analyze import Analyse, analyser
from agent_he.pipeline.extract import extraire
from agent_he.pipeline.match import Candidate, Contexte, correspondances_corpus
from agent_he.pipeline.normalize import normaliser_indication, normaliser_recette
from agent_he.pipeline.plan import planifier
from agent_he.pipeline.retrieve import recuperer_pages
from agent_he.pipeline.synthesize import reservoir, synthetiser
from agent_he.referentiel.huiles import Referentiel
from agent_he.referentiel.securite import TableSecurite
from agent_he.safety.checks import IndicationSource, assert_fiche_sure
from agent_he.safety.questionnaire import avertissements_profil, he_a_eviter, profil_exclu
from agent_he.safety.traceability import tracer
from agent_he.search.base import ErreurRecherche, Page, Recherche, Recuperateur
from agent_he.search.reliability import BADGES, Fiabilite
from agent_he.storage.audit import JournalAudit

__all__ = ["Agent", "Candidate", "Reglages", "Reponse"]


@dataclass
class Reglages:
    convention_gouttes_ml: int = 20
    recherche_ouverte: bool = False
    max_resultats: int = 5
    seuil_correspondance: float = 0.8
    volume_synthese_ml: float = 10.0
    analyse_llm: bool = True


@dataclass
class Reponse:
    fiche: Fiche
    sources: list[Source] = field(default_factory=list)
    controles: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    """Déroulé lisible (pages écartées, HE exclues, rejets) pour l'utilisateur et l'audit."""
    recette_ref: str | None = None
    """Référence stable de la recette proposée (journal d'usage, favoris)."""


@dataclass
class _Web:
    candidates: list[Candidate] = field(default_factory=list)
    tracees: list[Recette] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    indications: list[IndicationSource] = field(default_factory=list)


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
        audit: JournalAudit | None = None,
        journal: Journal | None = None,
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
        self.audit = audit
        self.journal = journal

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

    def source(self, url: str, titre: str | None = None, extrait: str = "") -> Source:
        return Source.model_validate(
            {
                "url": url,
                "titre": titre or url,
                "confiance": self.fiabilite.confiance(url),
                "extrait": extrait[:300],
            }
        )

    def web(self, ctx: Contexte, pages: list[Page]) -> _Web:
        """Priorité 1b : recettes publiées conformes, et recettes tracées pour la synthèse."""
        resultat = _Web()
        if not pages:
            return resultat
        demande = ctx.demande
        textes = {p.url: p.texte for p in pages}
        extraction = extraire(self.llm, demande.besoin, [str(v) for v in demande.voies], pages)
        resultat.contradictions = list(extraction.contradictions)
        indications: list[IndicationSource] = [
            i
            for brute in extraction.indications
            if (i := normaliser_indication(brute, self.referentiel, textes)) is not None
        ]
        resultat.indications = indications
        for brute in extraction.recettes:
            norm = normaliser_recette(brute, self.referentiel, textes)
            ctx.notes.extend(norm.notes)
            if norm.recette is None or norm.recette.voie not in demande.voies:
                continue
            trace = tracer(norm.recette, textes, self.referentiel)
            ctx.notes.extend(trace.retraits)
            if trace.recette is None:
                ctx.controles.append("tracabilite")
                continue
            # Les HE tracées alimentent la synthèse, même si la recette n'est pas reprise.
            resultat.tracees.append(trace.recette)
            if norm.huiles_exclues or trace.huiles_retirees:
                # Une recette verbatim amputée d'une HE n'est plus la recette publiée.
                ctx.notes.append(f"« {brute.nom_recette} » écartée : HE non retenue(s)")
                ctx.controles.append("tracabilite")
                continue
            candidate = ctx.controler(trace.recette, "publiee", indications=indications)
            if candidate is not None:
                resultat.candidates.append(candidate)
        return resultat

    def synthese(
        self, ctx: Contexte, tracees: list[Recette], indications: list[IndicationSource]
    ) -> Candidate | None:
        """Priorité 2 : synthèse tracée à partir des seules doses extraites."""
        doses = reservoir(tracees, self.reglages.convention_gouttes_ml)
        for voie in ctx.demande.voies:
            synthese = synthetiser(
                self.llm,
                ctx.demande.besoin,
                voie,
                doses,
                self.table,
                ctx.demande.questionnaire.age,
                volume_ml=self.reglages.volume_synthese_ml,
                convention_gouttes_ml=self.reglages.convention_gouttes_ml,
                plafonds_sources=self.plafonds_sources(indications, voie),
            )
            ctx.notes.extend(synthese.notes)
            if synthese.recette is None:
                continue
            candidate = ctx.controler(synthese.recette, "synthese", indications=indications)
            if candidate is not None:
                candidate.contradictions = [*synthese.contradictions, *candidate.contradictions]
                return candidate
            ctx.notes.append("Synthèse non conforme aux contrôles de sécurité : écartée")
        return None

    @staticmethod
    def plafonds_sources(indications: list[IndicationSource], voie: Voie) -> dict[str, float]:
        plafonds: dict[str, float] = {}
        for i in indications:
            if i.type == "plafond" and i.valeur is not None and i.voie in (None, voie):
                plafonds[i.he_id] = min(i.valeur, plafonds.get(i.he_id, i.valeur))
        return plafonds

    def ordonner(self, candidates: list[Candidate]) -> list[Candidate]:
        """Ordre de présentation des recettes **déjà conformes** (journal : ordonne seulement)."""
        if self.journal is None:
            return sorted(candidates, key=lambda c: c.pertinence, reverse=True)
        return classer(
            candidates,
            self.journal.lister(),
            recette=lambda c: c.recette,
            ref=lambda c: c.ref or c.recette.nom_recette,
            pertinence=lambda c: c.pertinence,
        )

    def retours_journal(self, candidate: Candidate) -> tuple[str | None, list[str]]:
        """Rappel des retours (« d'après ton journal… ») et réactions notées avec ses HE."""
        if self.journal is None:
            return None, []
        entrees = self.journal.lister()
        ref = candidate.ref or candidate.recette.nom_recette
        texte = rappel(stats_recette(entrees, ref))
        noms = {h.he_id: h.nom for h in candidate.recette.huiles}
        alertes: list[str] = []
        for entree, huiles in entrees:
            if entree.tolerance == Tolerance.AUCUNE:
                continue
            communes = [noms[h] for h in huiles if h in noms]
            if communes:
                niveau = "forte" if entree.tolerance == Tolerance.FORTE else "légère"
                alertes.append(
                    f"⚠️ Réaction {niveau} notée le {entree.horodatage:%d/%m/%Y} avec un "
                    f"mélange contenant {', '.join(communes)}."
                )
        return texte, alertes

    def fiche(self, demande: Demande, candidate: Candidate, sources: list[Source]) -> Fiche:
        citees = [s for s in sources if str(s.url) in candidate.recette.sources]
        sites = ", ".join(sorted({s.domaine for s in citees}))
        badges: list[str] = []
        if candidate.mode == "validee":
            badges.append(f"✅ Recette validée — source : {sites}")
        elif candidate.mode == "publiee":
            badges.append(f"📄 Recette publiée — source : {sites} (non relue)")
        else:
            badges.append(f"🧪 Synthèse tracée — sources : {sites}")
        badges += [f"{BADGES[s.confiance]} — {s.domaine}" for s in citees]
        avertissements = [*avertissements_profil(demande.questionnaire), *candidate.avertissements]
        if any(s.confiance == Confiance.NON_VERIFIE for s in citees):
            avertissements.append(
                "Source non vérifiée : dosages croisés avec la table de sécurité uniquement."
            )
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
        if self.journal is not None:
            # Le journal ne peut que restreindre : ses exclusions s'ajoutent aux autres.
            exclusions_perso = {
                **dict.fromkeys(exclusions_perso, "exclusion personnelle"),
                **(dict(exclusions_perso) if isinstance(exclusions_perso, Mapping) else {}),
                **self.journal.exclusions(),
            }
        reponse = self._repondre(demande, exclusions_perso)
        if self.audit is not None:
            self.audit.enregistrer(
                EntreeAudit(
                    demande=demande,
                    sources=[str(s.url) for s in reponse.sources],
                    mode=reponse.fiche.mode,
                    controles_declenches=sorted(set(reponse.controles)),
                )
            )
        return reponse

    def _repondre(
        self, demande: Demande, exclusions_perso: Mapping[str, str] | Collection[str]
    ) -> Reponse:
        refus = self.refus(demande)
        if refus is not None:
            return refus

        ctx = Contexte(
            demande=demande,
            table=self.table,
            referentiel=self.referentiel,
            convention_gouttes_ml=self.reglages.convention_gouttes_ml,
            exclusions_perso=exclusions_perso,
        )
        analyse = (
            analyser(self.llm, demande.besoin, demande.texte_libre)
            if self.reglages.analyse_llm
            else analyser(None, demande.besoin, demande.texte_libre)
        )

        # 1a — corpus validé, sans aucun appel web.
        corpus = self.corpus_valide(ctx, analyse)
        if corpus:
            choisie = self.ordonner(corpus)[0]
            sources = [self.source(u) for u in choisie.recette.sources]
            return self.finaliser(ctx, choisie, sources)

        # 1b — recettes publiées, puis 2 — synthèse tracée.
        try:
            pages = recuperer_pages(
                self.recherche,
                self.recuperateur,
                planifier(demande, analyse),
                self.fiabilite.liste_blanche(),
                ouverte=self.reglages.recherche_ouverte,
                max_resultats=self.reglages.max_resultats,
                notes=ctx.notes,
            )
            web = self.web(ctx, pages)
            sources = [self.source(p.url, p.titre, p.texte) for p in pages]
            if web.candidates:
                choisie = self.ordonner(web.candidates)[0]
                choisie.contradictions = [*web.contradictions, *choisie.contradictions]
                self.mettre_en_file(choisie, analyse, sources, ctx)
                return self.finaliser(ctx, choisie, sources)
            synthese = self.synthese(ctx, web.tracees, web.indications)
            if synthese is not None:
                synthese.contradictions = [*web.contradictions, *synthese.contradictions]
        except (ErreurRecherche, ErreurLLM) as exc:
            ctx.notes.append(str(exc))
            fiche = self.aucune(f"Recherche impossible : {exc}")
            return Reponse(fiche=fiche, controles=ctx.controles, notes=ctx.notes)
        if synthese is not None:
            return self.finaliser(ctx, synthese, sources)
        fiche = self.aucune(self.motif_aucune(ctx.notes))
        return Reponse(fiche, sources, ctx.controles, ctx.notes)

    def corpus_valide(self, ctx: Contexte, analyse: Analyse) -> list[Candidate]:
        if self.magasin is None or not analyse.besoins:
            return []
        texte = " ".join([*(str(b) for b in analyse.besoins), ctx.demande.besoin])
        try:
            return correspondances_corpus(
                ctx,
                self.magasin,
                self.corpus,
                analyse.besoins,
                texte,
                self.reglages.seuil_correspondance,
            )
        except ErreurIndex as exc:
            ctx.notes.append(str(exc))
            return []

    def mettre_en_file(
        self, choisie: Candidate, analyse: Analyse, sources: list[Source], ctx: Contexte
    ) -> None:
        if self.file_validation is None:
            return
        confiance = min(
            (s.confiance for s in sources if str(s.url) in choisie.recette.sources),
            key=list(Confiance).index,
            default=Confiance.NON_VERIFIE,
        )
        cid = self.file_validation.ajouter(choisie.recette, analyse.besoins, confiance)
        ctx.notes.append(f"Recette ajoutée à la file de validation ({cid})")

    def finaliser(self, ctx: Contexte, candidate: Candidate, sources: list[Source]) -> Reponse:
        """Construit la fiche et la soumet au validateur final (dernier rempart)."""
        fiche = self.fiche(ctx.demande, candidate, sources)
        fiche.rappel_journal, alertes = self.retours_journal(candidate)
        fiche.avertissements.extend(alertes)
        assert_fiche_sure(
            fiche,
            ctx.demande.questionnaire,
            self.table,
            self.referentiel,
            voies_demandees=ctx.demande.voies,
            exclusions_perso=set(ctx.exclusions_perso),
            sources_recuperees={str(s.url) for s in sources},
        )
        utilisees = [s for s in sources if str(s.url) in candidate.recette.sources]
        ref = candidate.ref or candidate.recette.nom_recette
        return Reponse(fiche, utilisees, ctx.controles, ctx.notes, recette_ref=ref)
