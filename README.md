# Agent_HE

Agent personnel d'aide à la création de synergies d'huiles essentielles : recherche de recettes
fiables, contrôles de sécurité déterministes, journal d'usage.

- Spécification : [`docs/specification.md`](docs/specification.md)
- Plan de codage : [`docs/plan.md`](docs/plan.md)
- Plan futur : [`docs/plan-futur.md`](docs/plan-futur.md)
- Règle de la table de sécurité : [`docs/regle-table-securite.md`](docs/regle-table-securite.md)

## Installation

Prérequis : Python 3.11+ et [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env   # puis renseigner les clés d'API
```

## Développement

```bash
uv run ruff check .          # lint
uv run ruff format .         # formatage
uv run mypy                  # typage strict (src/)
uv run pytest                # tests (aucun appel réseau)
```

Les tests marqués `live` appellent de vrais services et ne sont lancés qu'à la main :
`uv run pytest -m live`.

Le jeu d'évaluation (`tests/eval/cas.yaml`, 32 cas dont les cas pièges) est joué en CI sur
fixtures ; ses critères bloquants (0 dosage pour un profil exclu, 0 dépassement de plafond,
0 voie orale, 0 HE non tracée, 0 HE exclue, 0 relâchement dû au journal) ne sont jamais
désactivés.

## Table de sécurité

Les valeurs de `data/securite.yaml` sont saisies à la main depuis *Essential Oil Safety*
selon [`docs/regle-table-securite.md`](docs/regle-table-securite.md), jamais générées.

```bash
uv run agent-he securite controler                    # contrôles automatiques (§9)
uv run agent-he securite verifier SEC-0001 --conforme # ou --non-conforme "<point en échec>"
uv run agent-he securite valider SEC-0001
uv run agent-he securite rapport                      # docs/audit/securite-<date>.md
```

## Administration

Le menu **Administration** de l'interface édite les deux fichiers de configuration :

- **Boutiques (CGU)** — `data/boutiques.yaml` : liens vers le site, les CGU et le
  robots.txt de chaque boutique ; saisie de la page des CGU, de leur vérification (datée),
  du délai entre requêtes, de l'URL de recherche et du motif des liens produit. L'identifiant,
  le nom, l'URL, l'accès et l'extraction restent en lecture seule.
- **Table de sécurité** — `data/securite.yaml` : contrôles §9, création et correction des
  entrées (identifiant attribué automatiquement), puis vérification, validation ou retrait.
  Les champs de suivi et les empreintes sont en lecture seule ; modifier un champ de fond
  d'une entrée vérifiée ou validée la ramène en brouillon.

Chaque enregistrement est validé avant écriture et conserve les commentaires de tête du
fichier. En hébergement, ces pages écrivent dans le dossier `data/` monté depuis l'hôte :
penser à committer ces fichiers pour garder la traçabilité (règle P6).

## Utilisation

```bash
uv run streamlit run app/streamlit_app.py   # interface locale
uv run agent-he ask "mélange pour dormir" --voie cutanee --age adulte   # questionnaire : --grossesse, --asthme…
uv run agent-he journal add --melange "lavande fine:3:gouttes" --voie diffusion --tolerance aucune --efficacite 4
uv run agent-he journal exclure <he_id>   # confirme une proposition d'exclusion
uv run agent-he corpus reindex             # indexe data/recettes/ (Chroma, data/chroma/)
uv run agent-he corpus candidates          # recettes web en attente de relecture
uv run agent-he corpus valider <id> --besoin sommeil
uv run agent-he corpus rejeter <id> --motif "<raison>"
```

## Hébergement

L'outil est personnel et sans comptes : il ne doit jamais être ouvert publiquement sans
protection (le journal d'usage contient des données de santé). Toutes les données restent
dans `data/` (référentiel, table de sécurité, corpus, base SQLite, index Chroma), monté
depuis l'hôte : **sauvegarde ce dossier**.

### Sur ta machine

```bash
uv run streamlit run app/streamlit_app.py      # http://localhost:8501
```

Pour y accéder depuis ton téléphone sans rien exposer : installe
[Tailscale](https://tailscale.com) sur les deux appareils et ouvre
`http://<nom-de-la-machine>:8501`.

### Sur un serveur, avec Docker

Prérequis : Docker avec le plugin Compose, et un clone du dépôt sur le serveur.

```bash
cp .env.example .env            # clés d'API ; UID/GID = `id -u` / `id -g`
docker compose up -d --build    # appli sur 127.0.0.1:8501 (APP_BIND pour une autre adresse)
docker compose logs -f agent-he
```

- **Accès via Tailscale (recommandé)** : `APP_BIND=<adresse Tailscale du serveur>` dans
  `.env`, puis `docker compose up -d`. Rien n'est exposé sur Internet.
- **Accès par un nom de domaine** (HTTPS automatique et mot de passe, via Caddy) : faire
  pointer le domaine vers le serveur, ouvrir les ports 80 et 443, puis :

  ```bash
  docker compose run --rm caddy caddy hash-password     # saisir le mot de passe
  # dans .env : DOMAINE=…, AUTH_UTILISATEUR=…, AUTH_HASH='<empreinte>' (avec les apostrophes)
  docker compose --profile web up -d
  ```

Les commandes de la CLI s'exécutent dans le conteneur, sur les mêmes données :

```bash
docker compose exec agent-he agent-he securite controler
docker compose exec agent-he agent-he corpus reindex
```

Mise à jour : `git pull && docker compose up -d --build`.
