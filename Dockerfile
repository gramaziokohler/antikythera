FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /build

# Copy only the files required to build the package
COPY pyproject.toml README.md LICENSE tasks.py ./
COPY src/ src/

# Install tools needed to generate proto classes
RUN uv pip install --system invoke compas_pb grpcio-tools compas_invocations2

# Generate proto classes from .proto files
RUN invoke generate-proto-classes

# Build the wheel (artifacts include generated proto files)
RUN uv build --wheel --out-dir /dist

# ============================================================================

FROM python:3.13-slim

LABEL \
    org.opencontainers.image.authors="Chen Kasirer <kasirer@arch.ethz.ch>" 

# Without this, the actor launcher's startup output sits in Python's stdout
# buffer and `docker compose logs actors` stays empty for the life of the container.
ENV PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY --from=builder /dist /dist
# compas_timber is not a dependency of antikythera-sdk, but the models this image
# receives are mostly timber models, and loading them needs it.
RUN WHL=$(ls /dist/*.whl) && uv pip install --system "${WHL}[deployment,mcp,nats,zenoh]" compas_timber && rm -rf /dist

# Default: run the orchestrator. Override `command:` in docker-compose for actors.
CMD ["antikythera", "--host", "0.0.0.0", "--port", "8000"]
