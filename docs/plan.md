# Plan de codage — Agent IA Huiles Essentielles

> Plan d'implémentation dérivé de [`specification.md`](./specification.md).
> Chaque phase se termine par un livrable **testable** et une liste de critères d'acceptation.

---

## 0. Principes directeurs

1. **Sécurité avant fonctionnalité** : les garde-fous (profils à risque, plafonds de dilution, ingestion) sont du **code déterministe**, jamais délégués au seul LLM. Le LLM propose, le code valide.
2. **Traçabilité totale** : toute huile, tout dosage, toute précaution d'une fiche porte une référence vers une source récupérée. Un élément non traçable est **supprimé**, pas « corrigé ».
3. **Couches remplaçables** : LLM, moteur de recherche, base vectorielle et API produits sont derrière des interfaces (`Protocol`) pour pouvoir changer de fournisseur (Mistral ↔ OpenAI ↔ Claude, Tavily ↔ Brave…).
4. **Testable hors-ligne** : chaque connecteur externe a un *fake* / des fixtures enregistrées ; la CI ne fait aucun appel réseau.

---

## 1. Stack retenue

| Brique | Choix | Alternative prévue |
|---|---|---|
| Langage | Python 3.11+ | — |
| Gestion projet | `uv` (ou `pip` + `pyproject.toml`) | Poetry |
| LLM | Mistral API (`mistralai`), function calling + sortie JSON | OpenAI / Claude via la même interface `LLMClient` |
| Recherche web | Tavily (`tavily-python`, filtrage `include_domains`) | Brave Search API |
| Extraction de pages | `httpx` + `trafilatura` (texte principal) | `readability-lxml` |
| Modèles de données | `pydantic` v2 | — |
| Orchestration | Pipeline Python explicite (machine à états simple) ; LangGraph envisagé en phase 6 si besoin | LangGraph |
| Base vectorielle | Chroma (local, persistant) + embeddings Mistral | Qdrant / pgvector |
| Interface | Streamlit | Gradio |
| API produits | Rainforest API (Aromazon) ; PA-API si affiliation | ScraperAPI |
| Persistance (historique, favoris, audit) | SQLite (`sqlite3` / `SQLModel`) | Postgres |
| Config / secrets | `pydantic-settings` + `.env` (jamais commité) | — |
| Tests / qualité | `pytest`, `pytest-recording` (VCR), `ruff`, `mypy` | — |
| CI | GitHub Actions (lint + typecheck + tests) | — |

---

## 2. Arborescence cible

```
Agent_HE/
├── pyproject.toml
├── .env.example                 # MISTRAL_API_KEY, TAVILY_API_KEY, RAINFOREST_API_KEY…
├── README.md
├── docs/
│   ├── specification.md
│   └── plan.md
├── data/
│   ├── domains.yaml             # liste blanche + niveau de confiance par domaine
│   ├── safety_limits.yaml       # plafonds de dilution par HE (Tisserand & Young)
│   ├── risk_keywords.yaml       # mots-clés profils à risque
│   └── monographs/              # corpus pour la base vectorielle (phase 6)
├── src/agent_he/
│   ├── __init__.py
│   ├── config.py                # Settings (pydantic-settings)
│   ├── models.py                # Pydantic : Request, Source, Recipe, Oil, Sheet, Product…
│   ├── llm/
│   │   ├── base.py              # Protocol LLMClient
│   │   ├── mistral.py
│   │   └── prompts.py           # prompt système + prompts d'extraction/synthèse
│   ├── search/
│   │   ├── base.py              # Protocol SearchProvider
│   │   ├── tavily.py
│   │   ├── fetch.py             # téléchargement + nettoyage des pages
│   │   └── reliability.py       # classement des domaines (liste blanche)
│   ├── safety/
│   │   ├── profiles.py          # détection profils à risque
│   │   ├── limits.py            # table de plafonds + calcul gouttes ↔ %
│   │   ├── ingestion.py         # verrou voie orale
│   │   └── traceability.py      # vérification huile/dosage/précaution ↔ source
│   ├── pipeline/
│   │   ├── analyze.py           # étape 1 : analyse de la demande
│   │   ├── plan.py              # étape 2 : décomposition en requêtes
│   │   ├── retrieve.py          # étape 3 : recherche + filtrage
│   │   ├── extract.py           # étape 4 : extraction JSON des recettes
│   │   ├── match.py             # stratégie 🥇 recette officielle
│   │   ├── synthesize.py        # stratégie 🥈 synthèse tracée
│   │   └── agent.py             # orchestrateur : lancer_agent()
│   ├── products/
│   │   ├── base.py              # Protocol ProductProvider
│   │   ├── rainforest.py
│   │   └── compare.py           # normalisation prix/ml, détection chimiotype
│   ├── kb/
│   │   ├── ingest.py            # indexation des monographies/recettes validées
│   │   └── store.py             # wrapper Chroma
│   ├── storage/
│   │   ├── db.py                # SQLite
│   │   ├── audit.py             # log des sources par réponse
│   │   └── favorites.py
│   └── cli.py                   # `agent-he ask "…"`
├── app/
│   └── streamlit_app.py
└── tests/
    ├── fixtures/                # réponses Tavily/Mistral/Rainforest enregistrées
    ├── unit/
    └── integration/
```

---

## 3. Modèles de données (cœur du contrat)

À écrire **en premier** (`models.py`), car tout le reste en dépend.

```python
class Profile(StrEnum):      ADULTE, FEMME_ENCEINTE, ALLAITANTE, ENFANT, EPILEPTIQUE, ASTHMATIQUE, ANIMAL
class Route(StrEnum):        DIFFUSION, CUTANEE, BAIN, MASSAGE, INHALATION, ORALE
class TrustLevel(StrEnum):   INSTITUTIONNEL, SPECIALISE, BOUTIQUE, NON_VERIFIE

class UserRequest:   besoin: str; profil: Profile; voies: list[Route]; budget: float | None; texte_libre: str
class Source:        url; domaine; titre; trust: TrustLevel; extrait: str; date_recuperation
class OilDose:       he: str; nom_latin: str; chimiotype: str | None; gouttes: float | None;
                     source_refs: list[str]          # URLs justifiant huile + dosage
class Recipe:        nom_recette; huiles: list[OilDose]; base: str; volume_ml: float | None;
                     usage: str; voie: Route; precautions: list[TracedText]; sources: list[str]
class RecipeSheet:   recette: Recipe | None; mode: Literal["officielle", "synthese", "refus"];
                     badges; warnings: list[str]; contradictions: list[str]; produits: list[Product]
class Product:       titre; marque; prix; volume_ml; prix_ml; note; nb_avis;
                     chimiotype_mentionne: bool; origine; url; vendeur
class AuditEntry:    request_id; timestamp; requete; sources_utilisees; mode; refus_motif
```

Note : le champ `chimiote` de l'exemple JSON de la spec est normalisé en `chimiotype` + `nom_latin` (deux informations distinctes).

---

## 4. Phases d'implémentation

### Phase 0 — Socle projet (½ j)

- [ ] `pyproject.toml` (deps, scripts `agent-he`), `ruff`, `mypy --strict` sur `src/`.
- [ ] `config.py` + `.env.example` ; `.gitignore` (`.env`, `data/chroma/`, `*.sqlite`).
- [ ] `models.py` complet + tests de validation Pydantic.
- [ ] Workflow GitHub Actions : `ruff check`, `mypy`, `pytest`.

**Acceptation** : `pytest` vert en CI sur un repo vide de logique métier.

---

### Phase 1 — CLI minimale avec citations (spec J1, ~1 j)

- [ ] `llm/base.py` + `llm/mistral.py` : `complete(messages, json_schema=None)`, retries, timeout.
- [ ] `llm/prompts.py` : prompt système de la spec §6 **+** règle d'or de traçabilité (§5 « Interdit absolu »).
- [ ] `search/base.py` + `search/tavily.py` : `search(query, include_domains, max_results)` → `list[Source]`.
- [ ] `search/fetch.py` : récupération + extraction texte principal, cache disque (hash URL) pour limiter les coûts.
- [ ] `cli.py` : `agent-he ask "mélange pour dormir"` → réponse texte avec URLs citées.

**Acceptation** :
- La réponse contient ≥ 1 URL et chaque URL provient bien des résultats de recherche (test sur fixture).
- Aucune clé API n'est loggée.

---

### Phase 2 — Fiabilité des sources & sécurité déterministe (spec J2-3, ~2 j)

#### 2a. Liste blanche (`data/domains.yaml`, `search/reliability.py`)
- [ ] Domaines + niveau : `ansm.sante.fr`, `anses.fr`, `ema.europa.eu`, `nccih.nih.gov`, `pubmed.ncbi.nlm.nih.gov` → INSTITUTIONNEL ; `compagniedessens.fr`, `tisserandinstitute.org`, … → SPECIALISE ; boutiques → BOUTIQUE ; reste → NON_VERIFIE.
- [ ] Les requêtes Tavily passent d'abord avec `include_domains` (liste blanche), puis éventuellement un second passage ouvert dont les résultats sont marqués NON_VERIFIE.
- [ ] Badge UI dérivé du `TrustLevel`.

#### 2b. Garde-fous (`safety/`)
- [ ] `profiles.py` : détection par **(a)** le champ profil et **(b)** mots-clés dans le texte libre (`enceinte`, `grossesse`, `allaite`, `bébé`, `enfant`, `ans` + âge < 6, `épilep`, `asthm`, `chien`, `chat`, `cheval`…). Normalisation accents/casse. Tout match ⇒ `mode="refus"` des dosages + message de renvoi vers un professionnel.
- [ ] `limits.py` : chargement de `safety_limits.yaml` (HE → % max cutané, remarques). Fonctions `gouttes_vers_pourcentage(gouttes, volume_ml)` et `plafonner(recipe)`. Convention explicite (ex. 1 ml ≈ 20 gouttes) documentée et testée.
  - ⚠️ **Les valeurs de la table doivent être saisies depuis l'ouvrage Tisserand & Young (*Essential Oil Safety*, 2ᵉ éd.) avec la référence de page, et relues par un professionnel.** Aucune valeur ne doit être inventée par un développeur ou un LLM. Une HE absente de la table ⇒ pas de dosage cutané proposé (comportement « fail closed »).
- [ ] `ingestion.py` : toute recette `voie=ORALE` est refusée sauf si au moins une source citée est INSTITUTIONNEL (ANSM/EMA/NIH). Les fiches produits n'affichent jamais de mention d'ingestion.
- [ ] `traceability.py` : pour chaque `OilDose`, vérifier que le nom (FR ou latin, via table de synonymes) apparaît dans le texte d'au moins une source référencée ; pour chaque dosage, qu'un nombre de gouttes/% figure dans une source citée pour cette huile. Échec ⇒ l'élément est retiré et un warning est ajouté.

#### 2c. Extraction structurée (`pipeline/extract.py`)
- [ ] Le LLM convertit chaque page en `list[Recipe]` (sortie JSON validée par Pydantic, 1 retry en cas de JSON invalide).
- [ ] Le prompt impose de recopier les dosages **tels qu'écrits** et d'inclure l'URL de la page.

**Acceptation (tests unitaires obligatoires)** :
- Profil « femme enceinte » ou texte « je suis enceinte de 3 mois » ⇒ aucune goutte dans la fiche.
- Une recette à 10 % d'une HE plafonnée à 2 % ⇒ ramenée au plafond + warning.
- Une huile absente des sources injectée dans la sortie LLM simulée ⇒ supprimée.
- Recette orale sourcée uniquement par un blog ⇒ refusée.

---

### Phase 3 — Pipeline complet & stratégie de génération (~1,5 j)

Implémente l'arbre de décision de la spec §5.

- [ ] `analyze.py` : LLM → `UserRequest` normalisé (besoin, voies) ; le profil de sécurité est **recalculé par `safety/profiles.py`** (le LLM ne peut pas l'abaisser).
- [ ] `plan.py` : décomposition en 3 à 5 requêtes (recette, monographie HE, sécurité HE).
- [ ] `retrieve.py` : exécution parallèle (`asyncio`), dédoublonnage par URL, classement par `TrustLevel`.
- [ ] `match.py` — 🥇 **Recette officielle** :
  - score = critères couverts / critères demandés (besoin, voie, profil compatible, ingrédients disponibles) ;
  - seuil configurable, défaut **0,8** ;
  - si match : recette renvoyée **sans modification** (test d'égalité stricte avec l'extraction), badge « ✅ Recette officielle — source : [site] ».
- [ ] `synthesize.py` — 🥈 **Synthèse tracée** :
  - le LLM reçoit uniquement les huiles et dosages extraits (pas les pages brutes) et doit renvoyer pour chaque élément ses `source_refs` ;
  - passage obligatoire par `traceability` puis `limits.plafonner` ;
  - précautions = union des précautions des sources + remarques de `safety_limits.yaml` ;
  - warning permanent : « ⚠️ Mélange synthétisé par l'IA à partir des sources listées — vérifie les dosages avec un professionnel de santé avant utilisation. »
- [ ] Règle « au moins 2 sources » : si une seule source est disponible, la fiche est produite avec un warning « source unique — non croisée ».
- [ ] Détection des contradictions : mêmes huile + voie avec des dosages incompatibles entre sources ⇒ listées dans `contradictions`.
- [ ] `agent.py` : `lancer_agent(besoin, profil, voies, budget) -> RecipeSheet` + écriture d'une `AuditEntry`.

**Acceptation** :
- Tests d'intégration sur fixtures : 1 cas 🥇, 1 cas 🥈, 1 cas refus profil, 1 cas contradiction.
- Chaque fiche finale passe un validateur `assert_sheet_is_safe(sheet)` (réutilisé partout).

---

### Phase 4 — Interface Streamlit (spec J4, ~1 j)

- [ ] `app/streamlit_app.py` :
  - barre latérale : besoin, profil, voies, budget ;
  - zone chat libre (`st.chat_input`) — le texte passe aussi par la détection de profil ;
  - **bandeau sécurité permanent** en haut de page ;
  - rendu de fiche : tableau huiles (nom, chimiotype, gouttes), base, usage, précautions, sources cliquables avec badges, warnings et contradictions bien visibles ;
  - onglets : « Fiche », « Produits », « Sources », « Historique », « Favoris ».
- [ ] Indicateur de progression par étape du pipeline (`st.status`).
- [ ] Gestion d'erreurs utilisateur (clé API manquante, quota, aucune source trouvée).

**Acceptation** : test `streamlit.testing.v1.AppTest` qui soumet une requête (agent mocké) et vérifie la présence du bandeau, des sources et du warning en mode synthèse.

---

### Phase 5 — Comparaison produits (spec J5, ~1 j)

- [ ] `products/base.py` + `products/rainforest.py` : recherche par nom HE (+ nom latin), extraction titre, prix, note, nb avis, URL.
- [ ] `products/compare.py` :
  - parsing du volume (`10 ml`, `30ml`…) ⇒ prix/ml ;
  - détection mention nom latin / chimiotype / « HEBBD » / « HECT » dans le titre ou la description ⇒ critère qualité n°1 ;
  - tri : qualité d'abord, puis prix/ml.
- [ ] Boutiques HE (Aroma-Zone, Comptoir des Huiles…) : connecteur uniquement si API ou flux produit autorisé ; sinon scraping **éthique** (respect `robots.txt` et CGU, rate-limit, cache) — à valider au cas par cas avant implémentation.
- [ ] Carte UI : `Nom — origine — chimiotype — prix/ml — note — lien`.
- [ ] Filtre budget.
- [ ] Aucune mention d'ingestion sur les cartes produits.

**Acceptation** : tests de parsing volume/prix et de détection chimiotype sur un jeu de titres réels enregistrés.

---

### Phase 6 — Base de connaissances, historique & favoris (spec J6+, ~2 j)

- [ ] `kb/ingest.py` : indexation dans Chroma des monographies et **recettes validées** (avec métadonnées : URL, trust, besoin, voie, profil).
- [ ] `match.py` interroge d'abord la base vectorielle, puis le web (priorité 1 de la spec).
- [ ] `storage/` : historique des requêtes, favoris (sauvegarde d'une `RecipeSheet` sérialisée), consultation des audits.
- [ ] Commande `agent-he audit <request_id>` pour relire les sources d'une réponse.
- [ ] Optionnel : migration de l'orchestrateur vers LangGraph si le pipeline se complexifie (boucles de re-recherche).

**Acceptation** : une recette ajoutée à la base est retrouvée en mode 🥇 sans appel web (test avec search provider mocké qui échoue s'il est appelé).

---

### Phase 7 — Évaluation & validation métier (continu)

- [ ] Jeu d'évaluation `tests/eval/cases.yaml` (~30 demandes : sommeil, stress, digestion, peau, ambiance + cas pièges : enceinte, enfant 4 ans, chat, ingestion, huile inexistante).
- [ ] Métriques automatiques : % fiches avec ≥ 2 sources, % éléments tracés, 0 dépassement de plafond, 0 dosage sur profil à risque (ces deux derniers sont **bloquants** en CI).
- [ ] Revue des fiches par un aromathérapeute ; corrections reportées dans `safety_limits.yaml` et la base de recettes validées.

---

## 5. Stratégie de tests

| Niveau | Contenu | Réseau |
|---|---|---|
| Unitaire | safety/*, reliability, compare, parsing, modèles | Non |
| Intégration | pipeline complet avec `FakeLLM` / `FakeSearch` + fixtures VCR | Non |
| UI | `AppTest` Streamlit avec agent mocké | Non |
| Évaluation | `tests/eval`, marqueur `@pytest.mark.live`, lancé manuellement | Oui |

Les tests de sécurité (phase 2) sont écrits **avant** le code correspondant (TDD) et ne doivent jamais être désactivés.

---

## 6. Calendrier indicatif

| Phase | Durée | Correspondance spec |
|---|---|---|
| 0 Socle | ½ j | — |
| 1 CLI + citations | 1 j | J1 |
| 2 Fiabilité + sécurité + extraction | 2 j | J2-3 |
| 3 Pipeline & stratégie 🥇/🥈 | 1,5 j | §4-5 |
| 4 Streamlit | 1 j | J4 |
| 5 Produits | 1 j | J5 |
| 6 Base vectorielle, favoris | 2 j | J6+ |
| 7 Évaluation | continu | J6+ |

Total : ~9 jours de développement pour une V1 complète ; un prototype démontrable existe dès la fin de la phase 4.

---

## 7. Points ouverts / décisions à prendre

1. **API produits** : la spec mentionne « Aromazon PA-API » ; l'accès PA-API exige une affiliation avec ventes — on part sur Rainforest API en attendant. Confirmer le fournisseur et le budget.
2. **Table Tisserand & Young** : qui saisit et valide les valeurs (ouvrage nécessaire) ? Liste initiale d'HE couvertes (proposition : les 30 HE les plus courantes).
3. **Seuil de correspondance 🥇** : 0,8 par défaut, à calibrer sur le jeu d'évaluation.
4. **Boutiques HE** : vérifier pour chaque site les CGU / existence d'un flux produit avant tout scraping.
5. **Hébergement** : Streamlit Community Cloud (simple) vs conteneur Docker (contrôle des secrets et des logs d'audit).
6. **Mentions légales** : avertissement « ne remplace pas un avis médical » et politique de conservation des logs (RGPD si données de santé saisies en texte libre).
