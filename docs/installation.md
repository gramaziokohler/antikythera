# Installation

## Stable

Stable releases are available on PyPI and can be installed with pip.

```bash
pip install antikythera-sdk
```

To include the orchestrator deployment dependencies (FastAPI, Redis, MQTT, etc.):

```bash
pip install antikythera-sdk[deployment]
```

## Latest

The latest version can be installed from local source.

```bash
git clone https://github.com/gramaziokohler/antikythera.git
cd antikythera
pip install -e .
```

## Development

To install `antikythera` for development, install from local source with the "dev" requirements.

```bash
git clone https://github.com/gramaziokohler/antikythera.git
cd antikythera
pip install -e .[dev]
```
