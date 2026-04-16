FROM python:3.13-slim AS builder

ARG VERSION="0.1.0"

LABEL \
    org.opencontainers.image.authors="Chen Kasirer <kasirer@arch.ethz.ch>" \
    org.opencontainers.image.title="antikythera" \
    org.opencontainers.image.description="Back-end for Antikythera, a distributed task manager for digital fabrication processes" \
    org.opencontainers.image.url="https://github.com/gramaziokohler/antikythera" \
    org.opencontainers.image.documentation="https://gramaziokohler.github.io/antikythera/latest/" \
    org.opencontainers.image.source="https://github.com/gramaziokohler/antikythera" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.version=${VERSION}

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /build

# Copy only the files required to build the package
COPY pyproject.toml requirements.txt requirements-dev.txt requirements-orchestrator.txt README.md LICENSE ./
COPY src/ src/

# Proto files are pre-generated and packaged with the source; just build the wheel.
RUN uv build --wheel --out-dir /dist

# ============================================================================

FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY --from=builder /dist /dist
RUN WHL=$(ls /dist/*.whl) && uv pip install --system "${WHL}[deployment]" && rm -rf /dist

# Default: run the orchestrator. Override `command:` in docker-compose for agents.
CMD ["antikythera", "--host", "0.0.0.0", "--port", "8000"]
