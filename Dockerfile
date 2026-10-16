# Image de l'interface Streamlit (outil personnel, voir README « Hébergement »).
# Image de base remplaçable (ex. un miroir : --build-arg IMAGE_PYTHON=mirror.gcr.io/library/python:3.11-slim).
ARG IMAGE_PYTHON=python:3.11-slim
FROM ${IMAGE_PYTHON}

RUN pip install --no-cache-dir "uv>=0.11,<0.12"

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    ANONYMIZED_TELEMETRY=False

WORKDIR /app

# Dépendances d'abord (couche mise en cache tant que uv.lock ne change pas).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY app ./app
RUN uv sync --locked --no-dev

# Données de référence par défaut ; en production, data/ est monté depuis l'hôte
# (docker-compose.yml) pour conserver le journal, l'historique et l'index.
COPY data ./data

RUN useradd --uid 1000 --create-home agent && chown -R agent:agent /app/data
USER agent

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)"

CMD ["streamlit", "run", "app/streamlit_app.py"]
