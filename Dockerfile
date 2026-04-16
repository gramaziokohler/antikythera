FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# TODO: Remove once new compas_pb@invoc_arch is released
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Install build-system requirements.
# The hatch build hook (hatch_build.py) runs `invoke generate-proto-classes`
# which downloads protoc and generates the *_pb2.py files. These generated
# files are gitignored and must be produced during the build.
# --no-build-isolation lets the hook use these already-installed tools.
RUN uv pip install --system \
    hatchling \
    hatch-requirements-txt \
    invoke \
    compas_invocations2 \
    compas_pb>=0.4.10 \
    grpcio-tools

# Copy only the files required to build the package
COPY pyproject.toml requirements.txt requirements-dev.txt requirements-orchestrator.txt hatch_build.py tasks.py README.md LICENSE ./
COPY src/ src/

# Build the wheel; the hatch hook will download protoc and generate antikythera_pb2.py
RUN uv build --wheel --no-build-isolation --out-dir /dist

# ============================================================================

FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# TODO: Remove once new compas_pb@invoc_arch is released
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /dist /dist
RUN WHL=$(ls /dist/*.whl) && uv pip install --system "${WHL}[deployment]" && rm -rf /dist

# Default: run the orchestrator. Override `command:` in docker-compose for agents.
CMD ["antikythera", "--host", "0.0.0.0", "--port", "8000"]
