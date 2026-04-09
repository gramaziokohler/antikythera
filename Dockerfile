FROM python:3.13-slim

# TODO: Remove once new compas_pb@invoc_arch is released
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install build-system requirements.
# The hatch build hook (hatch_build.py) runs `invoke generate-proto-classes`
# which downloads protoc and generates the *_pb2.py files. These generated
# files are gitignored and must be produced during the build.
# --no-build-isolation lets the hook use these already-installed tools.
RUN pip install --no-cache-dir \
    hatchling \
    hatch-requirements-txt \
    invoke \
    compas_invocations2 \
    "git+https://github.com/gramaziokohler/compas_pb@invoc_arch" \
    grpcio-tools \
    compas_timber==2.1.1-rc1

COPY . .

# Install the antikythera package (orchestrator + agents + library).
# --no-build-isolation uses the already-installed build tools above.
# The build hook will download protoc and generate antikythera_pb2.py.
RUN pip install --no-cache-dir --no-build-isolation .

# Default: run the orchestrator. Override `command:` in docker-compose for agents.
CMD ["antikythera", "--host", "0.0.0.0", "--port", "8000"]
