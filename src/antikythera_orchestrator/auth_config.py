"""Render and validate Dex configuration for the Compose auth profile."""

import os
import re
from pathlib import Path
from typing import Mapping
from typing import Optional
from urllib.parse import urlparse

PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")

SECRET_FILES = {
    "OAUTH2_PROXY_CLIENT_SECRET": "/run/secrets/oauth2_proxy_client_secret",
    "GOOGLE_CLIENT_SECRET": "/run/secrets/google_client_secret",
    "GITHUB_CLIENT_SECRET": "/run/secrets/github_client_secret",
}


def _read_secret(path: str) -> str:
    try:
        value = Path(path).read_text().strip()
    except OSError as error:
        raise ValueError(f"Cannot read required auth secret {path}: {error}") from error
    if not value:
        raise ValueError(f"Required auth secret {path} is empty")
    return value


def render_dex_config(template: str, environment: Optional[Mapping[str, str]] = None) -> str:
    """Substitute public settings and Docker secrets into a Dex template.

    Every placeholder is required. Refusing to emit a partially rendered file
    makes missing provider credentials fail during ``dex-init`` instead of much
    later when a user selects a broken provider.
    """
    env = os.environ if environment is None else environment
    values = dict(env)

    required_names = set(PLACEHOLDER.findall(template))
    for name, default_path in SECRET_FILES.items():
        if name not in required_names:
            continue
        direct_value = values.get(name, "").strip()
        if not direct_value:
            values[name] = _read_secret(values.get(f"{name}_FILE", default_path))

    public_url = values.get("AUTH_PUBLIC_URL", "").strip()
    parsed_url = urlparse(public_url)
    if (
        parsed_url.scheme not in ("http", "https")
        or not parsed_url.netloc
        or parsed_url.path not in ("", "/")
        or parsed_url.params
        or parsed_url.query
        or parsed_url.fragment
        or parsed_url.username
        or parsed_url.password
    ):
        raise ValueError("AUTH_PUBLIC_URL must be an http(s) origin without a path")
    values["AUTH_PUBLIC_URL"] = public_url.rstrip("/")

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = values.get(name, "").strip()
        if not value:
            raise ValueError(f"Required auth setting {name} is missing")
        return value

    rendered = PLACEHOLDER.sub(replace, template)
    if PLACEHOLDER.search(rendered):  # defensive; replace currently catches all
        raise ValueError("Dex configuration still contains unresolved placeholders")
    return rendered


def main() -> None:
    template_path = Path(os.getenv("DEX_CONFIG_TEMPLATE", "/tmpl/dex.yaml"))
    output_path = Path(os.getenv("DEX_CONFIG_OUTPUT", "/rendered/config.yaml"))
    rendered = render_dex_config(template_path.read_text())
    output_path.write_text(rendered)
    print(f"dex config rendered to {output_path}")


if __name__ == "__main__":
    main()
