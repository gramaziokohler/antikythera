"""Verify the development OIDC login, session, and forwarded identity flow."""

from __future__ import annotations

import argparse
import json
from http.cookiejar import CookieJar
from html.parser import HTMLParser
from urllib.parse import urlencode
from urllib.parse import urljoin
from urllib.request import HTTPCookieProcessor
from urllib.request import Request
from urllib.request import build_opener


class _LoginFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "form" or self.action is not None:
            return
        attributes = dict(attrs)
        if attributes.get("method", "get").lower() == "post":
            self.action = attributes.get("action")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--email", default="kilgore@kilgore.trout")
    parser.add_argument("--password", default="password")
    args = parser.parse_args()

    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    login_page = opener.open(f"{args.base_url}/")
    form = _LoginFormParser()
    form.feed(login_page.read().decode())
    if not form.action:
        raise RuntimeError(f"Dex login form not found at {login_page.geturl()}")

    credentials = urlencode({"login": args.email, "password": args.password}).encode()
    opener.open(Request(urljoin(login_page.geturl(), form.action), data=credentials)).read()

    identity = json.load(opener.open(f"{args.base_url}/api/whoami"))
    expected = {"authenticated": True, "email": args.email}
    if any(identity.get(key) != value for key, value in expected.items()):
        raise RuntimeError(f"Unexpected authenticated identity: {identity}")
    print(f"authenticated as {identity['email']}")


if __name__ == "__main__":
    main()
