# syntax=docker/dockerfile:1.7

FROM node:24.20.0-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.14.6-slim-bookworm AS python-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

FROM python-base AS runtime-deps
COPY requirements.txt ./
RUN grep -vE '^(matplotlib|pytest|httpx2)==' requirements.txt > requirements-runtime.txt \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install -r requirements-runtime.txt \
    && find /opt/venv/lib -depth -type d -name tests -path "*site-packages/*" -exec rm -rf {} + \
    && /opt/venv/bin/pip uninstall -y pip \
    && find /opt/venv -name "*.pyi" -delete

FROM python-base AS warehouse
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY run.py pytest.ini ./
COPY src/ src/
COPY sql/ sql/
COPY mieru/ mieru/
COPY scripts/build_runtime_db.py scripts/
COPY baselines/ baselines/
COPY tests/__init__.py tests/test_baseline_regression.py tests/
RUN mkdir -p data/raw outputs \
    && python run.py \
    && python -m pytest -q -p no:cacheprovider tests/test_baseline_regression.py \
    && PYTHONPATH=. python scripts/build_runtime_db.py data/marketplace.duckdb /build/runtime/marketplace.duckdb

FROM python:3.14.6-slim-bookworm AS runtime
ARG VERSION=dev
LABEL org.opencontainers.image.title="MIERU" \
      org.opencontainers.image.description="Upload a sales spreadsheet and get explainable analytics. Non-commercial portfolio project." \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="MIT AND CC-BY-NC-SA-4.0"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    MIERU_ENV=production \
    MIERU_HOST=0.0.0.0 \
    MIERU_PORT=8000 \
    MIERU_DATA_DIR=/app/var \
    MIERU_MAX_UPLOAD_MB=20 \
    MIERU_MAX_UPLOAD_ROWS=250000 \
    MIERU_DATASET_TTL_MINUTES=60 \
    MIERU_PROCESSING_WORKERS=1 \
    MIERU_PROCESSING_QUEUE_LIMIT=2 \
    MIERU_DUCKDB_MEMORY_LIMIT=512MB \
    MIERU_DUCKDB_THREADS=1
RUN groupadd --system --gid 10001 mieru \
    && useradd --system --uid 10001 --gid mieru --home-dir /app --shell /usr/sbin/nologin mieru
WORKDIR /app
COPY --from=runtime-deps /opt/venv /opt/venv
COPY --chmod=0555 mieru/ mieru/
COPY --chmod=0555 src/ src/
COPY --chmod=0555 baselines/ baselines/
COPY --chmod=0555 LICENSE NOTICE ./
COPY --chmod=0555 --from=warehouse /build/runtime/marketplace.duckdb data/marketplace.duckdb
COPY --chmod=0555 --from=warehouse /app/outputs/ outputs/
COPY --chmod=0555 --from=frontend /build/frontend/dist/ frontend/dist/
RUN mkdir -p var && chown mieru:mieru var
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"]
CMD ["python", "-m", "mieru"]
