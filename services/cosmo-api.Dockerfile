# Cosmoport 2.0 — Cosmo API Dockerfile
#
# FastAPI modular monolith. Собирает orchestrator/ + alembic/.
# Точка входа: orchestrator.cosmo.api.main:app
#
# Build:
#   docker build -f services/cosmo-api.Dockerfile -t cosmo-api:local ..
#
# Зависит от: requirements.txt в корне репозитория.
# После старта проверка: curl http://localhost:8100/live

FROM python:3.12-slim

WORKDIR /app

# ── Scanner tools: trivy + syft + grype (COS-171/172/183, digest-pinned) ─
#
# Сканеры устанавливаются ЕДИНСТВЕННО на этапе сборки образа (никакой сети
# в runtime). Каждый тарбол проверяется по sha256 перед распаковкой — подмена
# релиза ловится на сборке, а не на проде.
#
# TRIVY_CACHE_DIR / GRYPE_DB_CACHE_DIR — единый во всех трёх точках
# (правило Boss'а #2): download (build) == ENV == volume в compose.
ARG TRIVY_VERSION=0.74.0
ARG TRIVY_SHA256=2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a
ARG SYFT_VERSION=1.20.0
ARG SYFT_SHA256=689e12c5cbf67521ce61b9c126068f9eaabe1223e77971b2fede50033ff6b5cc
ARG GRYPE_VERSION=0.119.0
ARG GRYPE_SHA256=3fa2dc4b924621ab65404cf08d0b8438d896d80ab949c9d5a4ca283c36004c9b
# grype DB (~2.9GB unpacked) держим в образе ТОЛЬКО как seed-tar; распакованную
# копию удаляем (entrypoint засеет её в volume) — иначе образ пухнет на ~3GB.

ENV TRIVY_CACHE_DIR=/var/lib/trivy \
    GRYPE_DB_CACHE_DIR=/var/lib/grype

RUN set -eux \
 && apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && curl -fsSL "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" -o /tmp/trivy.tgz \
 && echo "${TRIVY_SHA256}  /tmp/trivy.tgz" | sha256sum -c - \
 && tar -xzf /tmp/trivy.tgz -C /usr/local/bin trivy \
 && curl -fsSL "https://github.com/anchore/syft/releases/download/v${SYFT_VERSION}/syft_${SYFT_VERSION}_linux_amd64.tar.gz" -o /tmp/syft.tgz \
 && echo "${SYFT_SHA256}  /tmp/syft.tgz" | sha256sum -c - \
 && tar -xzf /tmp/syft.tgz -C /usr/local/bin syft \
 && curl -fsSL "https://github.com/anchore/grype/releases/download/v${GRYPE_VERSION}/grype_${GRYPE_VERSION}_linux_amd64.tar.gz" -o /tmp/grype.tgz \
 && echo "${GRYPE_SHA256}  /tmp/grype.tgz" | sha256sum -c - \
 && tar -xzf /tmp/grype.tgz -C /usr/local/bin grype \
 && chmod +x /usr/local/bin/trivy /usr/local/bin/syft /usr/local/bin/grype \
 && rm -f /tmp/trivy.tgz /tmp/syft.tgz /tmp/grype.tgz \
 && trivy image --download-db-only --cache-dir "${TRIVY_CACHE_DIR}" \
 && grype db update \
 && mkdir -p /opt \
 && tar -czf /opt/trivy-db-seed.tar.gz -C "${TRIVY_CACHE_DIR}" . \
 && tar -czf /opt/grype-db-seed.tar.gz -C "${GRYPE_DB_CACHE_DIR}" . \
 && rm -rf "${GRYPE_DB_CACHE_DIR}" \
 && trivy --version \
 && grype --version \
 && syft version | head -1

# ── Dependencies layer (cacheable) ────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application layer ─────────────────────────────────────────────────
COPY orchestrator/ ./orchestrator/
COPY alembic.ini .
COPY alembic/ ./alembic/

# ── Runtime ───────────────────────────────────────────────────────────
EXPOSE 8100

# Entrypoint: Alembic migrations → uvicorn
COPY services/entrypoint.sh /entrypoint.sh
# Normalize line endings (Windows checkout может дать CRLF -> сломанный shebang).
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]