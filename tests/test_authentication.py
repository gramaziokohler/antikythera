import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from antikythera import config
from antikythera_orchestrator.api import app
from antikythera_orchestrator.auth_config import render_dex_config

DEX_TEMPLATE = """\
issuer: ${AUTH_PUBLIC_URL}/dex
client: ${OAUTH2_PROXY_CLIENT_SECRET}
google_id: ${GOOGLE_CLIENT_ID}
google_secret: ${GOOGLE_CLIENT_SECRET}
github_id: ${GITHUB_CLIENT_ID}
github_secret: ${GITHUB_CLIENT_SECRET}
"""

REPOSITORY_ROOT = Path(__file__).parents[1]


def test_whoami_ignores_forwarded_headers_unless_edge_auth_is_enabled(monkeypatch):
    monkeypatch.setattr(config, "TRUST_AUTH_HEADERS", False)
    response = TestClient(app).get(
        "/whoami",
        headers={"X-Auth-Request-Email": "spoofed@example.com", "X-Auth-Request-User": "spoofed"},
    )

    assert response.status_code == 200
    assert response.json() == {"authenticated": False, "email": None, "user": None}


def test_whoami_returns_identity_from_trusted_edge(monkeypatch):
    monkeypatch.setattr(config, "TRUST_AUTH_HEADERS", True)
    response = TestClient(app).get(
        "/whoami",
        headers={"X-Auth-Request-Email": "user@example.com", "X-Auth-Request-User": "Example User"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "email": "user@example.com",
        "user": "Example User",
    }


def test_render_dex_config_requires_all_provider_settings(tmp_path):
    for name, value in {
        "oauth": "shared-secret",
        "google": "google-secret",
        "github": "github-secret",
    }.items():
        path = tmp_path / name
        path.write_text(value)

    rendered = render_dex_config(
        DEX_TEMPLATE,
        {
            "AUTH_PUBLIC_URL": "https://antikythera.example.org",
            "OAUTH2_PROXY_CLIENT_SECRET_FILE": str(tmp_path / "oauth"),
            "GOOGLE_CLIENT_ID": "google-id",
            "GOOGLE_CLIENT_SECRET_FILE": str(tmp_path / "google"),
            "GITHUB_CLIENT_ID": "github-id",
            "GITHUB_CLIENT_SECRET_FILE": str(tmp_path / "github"),
        },
    )

    assert "${" not in rendered
    assert "issuer: https://antikythera.example.org/dex" in rendered
    assert "google_secret: google-secret" in rendered


def test_render_dex_config_fails_for_missing_provider_id(tmp_path):
    for name in ("oauth", "google", "github"):
        (tmp_path / name).write_text("secret")

    environment = {
        "AUTH_PUBLIC_URL": "https://antikythera.example.org",
        "OAUTH2_PROXY_CLIENT_SECRET_FILE": str(tmp_path / "oauth"),
        "GOOGLE_CLIENT_ID": "",
        "GOOGLE_CLIENT_SECRET_FILE": str(tmp_path / "google"),
        "GITHUB_CLIENT_ID": "github-id",
        "GITHUB_CLIENT_SECRET_FILE": str(tmp_path / "github"),
    }

    with pytest.raises(ValueError, match="GOOGLE_CLIENT_ID"):
        render_dex_config(DEX_TEMPLATE, environment)


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker Compose CLI is not installed")
def test_auth_compose_profile_closes_bypass_ports():
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.auth.dev.yml",
            "config",
            "--format",
            "json",
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    services = json.loads(result.stdout)["services"]

    assert "ports" not in services["redis"]
    assert "ports" not in services["orchestrator"]
    assert "ports" not in services["mcp-server"]
    assert "secrets" not in services["dex-init"]
    assert "secrets" not in services["oauth2-proxy"]
    assert services["frontend"]["ports"][0]["published"] == "80"
    assert services["mqtt-broker"]["ports"] == [
        {
            "mode": "ingress",
            "host_ip": "127.0.0.1",
            "target": 1883,
            "published": "1883",
            "protocol": "tcp",
        }
    ]
