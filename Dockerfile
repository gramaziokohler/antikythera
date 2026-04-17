FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /build

# Copy only the files required to build the package
COPY pyproject.toml requirements.txt requirements-dev.txt requirements-orchestrator.txt README.md LICENSE ./
COPY src/ src/

# Proto files are pre-generated and packaged with the source; just build the wheel.
RUN uv build --wheel --out-dir /dist

# ============================================================================

FROM python:3.13-slim

LABEL \
    org.opencontainers.image.authors="Chen Kasirer <kasirer@arch.ethz.ch>" 

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY --from=builder /dist /dist
RUN WHL=$(ls /dist/*.whl) && uv pip install --system "${WHL}[deployment]" && rm -rf /dist

# Default: run the orchestrator. Override `command:` in docker-compose for agents.
CMD ["antikythera", "--host", "0.0.0.0", "--port", "8000"]
