# Agent_HE

Agent personnel d'aide à la création de synergies d'huiles essentielles : recherche de recettes
fiables, contrôles de sécurité déterministes, journal d'usage.

- Spécification : [`docs/specification.md`](docs/specification.md)
- Plan de codage : [`docs/plan.md`](docs/plan.md)
- Plan futur : [`docs/plan-futur.md`](docs/plan-futur.md)

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
