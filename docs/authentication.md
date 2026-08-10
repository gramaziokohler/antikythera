# Authentication

Antikythera ships **without authentication by default**. For public / internet-facing
deployments you can plug an **optional social-login layer** on top of the stack — Google and
GitHub today, with Apple and SWITCH edu-ID as future connectors — restricted to an **email
allowlist**. There is no home-grown username/password system.

This is the operator guide. The design rationale is recorded separately:

- [ADR 0001: Optional edge authentication](adr/0001-optional-edge-authentication.md)
- [ADR 0002: Lightweight collaborator authorization](adr/0002-lightweight-collaborator-authorization.md)
- [ADR 0003: Separate browser and machine security boundaries](adr/0003-browser-and-machine-security-boundaries.md)
- [ADR 0004: Server-side sessions and file-backed secrets](adr/0004-auth-sessions-and-secrets.md)

## Runtime topology

```
browser ──▶ nginx (single public origin, TLS)
              ├─ auth_request ─▶ oauth2-proxy ──OIDC──▶ dex ──▶ { Google, GitHub, Apple, edu-ID }
              ├─ /            ─▶ static React app        (served only if authorised)
              ├─ /api/, SSE   ─▶ orchestrator:8000       (served only if authorised)
              └─ /mqtt        ─▶ mqtt-broker:8083 (ws)   (served only if authorised)
```

- **[oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/)** holds the session and enforces
  the allowlist. nginx calls it via `auth_request`.
- **[Dex](https://dexidp.io/)** presents the provider chooser and brokers Google/GitHub OIDC for
  oauth2-proxy.

Relevant files:

| File | Purpose |
|------|---------|
| `docker-compose.auth.yml` | Adds `dex` + `oauth2-proxy`, swaps in the auth nginx config |
| `config/auth/nginx.auth.conf` | nginx with the `auth_request` gate (mounted over the frontend) |
| `config/auth/dex.yaml` | dex issuer, oauth2-proxy client, provider connectors |
| `config/auth/allowlist.txt` | Allowed email addresses |
| `.env.auth.example` | Template for secrets → copy to `.env.auth` |

## Running with / without auth

```bash
# Auth OFF (local dev, trusted network) — unchanged:
docker compose up

# Auth ON (public deployment):
docker compose --env-file .env.auth -f docker-compose.yml -f docker-compose.auth.yml up
```

nginx stays the only browser-facing entry point on `:80`; Dex, oauth2-proxy, Redis, the REST API,
MQTT-over-WebSocket, and MCP are internal-only. Raw MQTT is retained for agents but bound to
`127.0.0.1:1883` by default. Set `AUTH_MQTT_BIND_ADDRESS` to a private/VPN interface only after
configuring broker credentials; do not expose the anonymous broker publicly.

The override uses Compose's `!reset` / `!override` tags and therefore requires Docker Compose
2.24.4 or newer. A TLS terminator in front of nginx must **replace**, rather than append to,
`X-Forwarded-Proto` and send `https` for secure requests.

## One-time setup

### 1. Secrets

```bash
cp .env.auth.example .env.auth
```

Create the Docker secret files first:

```bash
mkdir -p secrets/auth
umask 077
openssl rand -base64 32 | tr -d '\n' > secrets/auth/oauth2-proxy-client-secret
openssl rand 32 > secrets/auth/oauth2-proxy-cookie-secret
```

After registering Google and GitHub in step 3, write each provider secret without a trailing
newline:

```bash
printf '%s' 'google-secret-here' > secrets/auth/google-client-secret
printf '%s' 'github-secret-here' > secrets/auth/github-client-secret
chmod 600 secrets/auth/*
```

Then fill in `.env.auth`:

- `AUTH_PUBLIC_URL` — the exact public origin, e.g. `https://antikythera.example.ethz.ch`
  (scheme, no path or trailing slash).
- `GOOGLE_CLIENT_ID` and `GITHUB_CLIENT_ID` — the non-secret provider client IDs.
- The four `*_FILE` settings — paths to the Docker secret files above.
- Optional cookie lifetime/domain settings and `AUTH_MQTT_BIND_ADDRESS`.

Both Google and GitHub connectors are active in the production profile. `dex-init` validates every
ID and secret and refuses to emit a partial configuration, so missing credentials fail at startup.

For a Google-only local test, leave the GitHub values empty and add
`-f docker-compose.auth.google.yml` after the normal auth override. This selects a narrower Dex
template and removes the unused GitHub secret mount; the default production profile continues to
require both providers.

### 2. Access control (who is allowed in)

Successful login is not enough — the email must also be allowed:

- **Individual addresses (strict allowlist):** list them in `config/auth/allowlist.txt` (one per
  line) and leave `OAUTH2_PROXY_EMAIL_DOMAINS` **empty**. Only listed addresses get in.
- **Whole domain:** set `OAUTH2_PROXY_EMAIL_DOMAINS=ethz.ch` in `.env.auth`.

The domain setting and the allowlist file are **OR-combined**: a user is allowed if they match the
domain *or* are in the file. **Never set `OAUTH2_PROXY_EMAIL_DOMAINS=*`** — it matches every
domain and therefore lets *any* authenticated account in, silently bypassing the allowlist. Anyone
who logs in with a non-allowed email gets a **403**.

### 3. Register the OAuth apps

For each provider, set the **redirect / callback URL to `${AUTH_PUBLIC_URL}/dex/callback`**. Put the
client ID in `.env.auth` and the client secret in its Docker secret file.

- **GitHub** — <https://github.com/settings/developers> → *New OAuth App*.
  Homepage: `${AUTH_PUBLIC_URL}` · Callback: `${AUTH_PUBLIC_URL}/dex/callback`.
  → `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`.
- **Google** — <https://console.cloud.google.com/apis/credentials> → *OAuth client ID* → *Web
  application*. Authorized redirect URI: `${AUTH_PUBLIC_URL}/dex/callback`.
  → `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.

Apple is a future connector rather than an active provider. Adding it requires its connector,
secret declaration/mount, and renderer mapping; its client secret is a signed JWT that needs
rotation.

### 4. Start it

```bash
docker compose --env-file .env.auth -f docker-compose.yml -f docker-compose.auth.yml up --build
```

Visit `${AUTH_PUBLIC_URL}` → you should be redirected to the dex chooser.

### Testing the real Google provider on localhost

Google permits plain HTTP for localhost callbacks. Register a Web OAuth client with the exact
redirect URI `http://localhost/dex/callback`, set `AUTH_PUBLIC_URL=http://localhost` and
`OAUTH2_PROXY_COOKIE_SECURE=false`, then start the Google-only profile:

```bash
docker compose --env-file .env.auth \
  -f docker-compose.yml \
  -f docker-compose.auth.yml \
  -f docker-compose.auth.google.yml \
  up -d --build
```

The Google client ID belongs in `.env.auth`; keep its client secret only in the file named by
`GOOGLE_CLIENT_SECRET_FILE`. The login email must also appear in `config/auth/allowlist.txt` or
match `OAUTH2_PROXY_EMAIL_DOMAINS`.

## Adding SWITCH edu-ID later

edu-ID is a standard OIDC provider, but it is not wired into the production profile yet:

1. Register an OIDC client with SWITCH; redirect URI `${AUTH_PUBLIC_URL}/dex/callback`.
2. Add its connector, client ID environment value, Docker secret declaration/mount, and renderer
   secret mapping (confirm the current issuer URL with SWITCH).
3. Recreate `dex-init` and Dex. "SWITCH edu-ID" then appears on the chooser.

## Verifying the auth flow locally (no real OAuth apps)

A dev override replaces the social providers with Dex's built-in **local login** so you can
exercise the entire gate → login form → allowlist → session path on `http://localhost` without
registering anything:

```bash
docker compose -f docker-compose.auth.dev.yml up --build
```

Then open <http://localhost>. You are redirected through oauth2-proxy to the Dex login form. Use
email `kilgore@kilgore.trout` and password `password`; after login, the app's user badge shows that
email address.
Files: `docker-compose.auth.dev.yml`, `docker-compose.auth.dev.override.yml`,
`config/auth/dex.dev.yaml`, `config/auth/allowlist.dev.txt`, and `.env.auth.dev` (all dev-only, no
secrets). To see a rejection, remove that email from
`allowlist.dev.txt` and retry — login ends in **403**.

For real providers on plain HTTP, set `AUTH_PUBLIC_URL=http://localhost` and
`OAUTH2_PROXY_COOKIE_SECURE=false` in `.env.auth`, but note GitHub/Google still require their real
callback URLs, so end-to-end testing of those is easiest against the real public hostname.

## How the dex config is rendered

dex only substitutes environment variables in a few config sub-sections (not the top-level
`issuer`/`staticClients`). A one-shot `dex-init` container uses
`antikythera_orchestrator.auth_config` to validate the public origin, read provider credentials from
Docker secrets, reject unresolved values, and render the final configuration into a shared volume.
Recreate `dex-init` and Dex after changing its template or credentials.

## Sessions and logout

oauth2-proxy stores OIDC session data in Redis database 1 and keeps only a small session reference
in the browser cookie. Defaults are a 12-hour session with refresh after one hour; both are
configurable in `.env.auth`. nginx propagates refreshed cookies from its auth subrequests.

The frontend checks the session on startup, every 30 seconds, when the tab becomes visible, and on
window focus. Any API `401` immediately restarts login. “Sign out” clears the Antikythera session
and lands on `/signed-out.html`; it does **not** sign the user out of Google or GitHub, because those
providers do not expose one uniform federated logout operation through Dex.

## Authorization scope

An allowlisted user is a **collaborator** with access to all shared sessions, blueprints, models,
and actions. See [ADR 0002](adr/0002-lightweight-collaborator-authorization.md) for the scope and
the deliberately deferred `member` / `admin` extension.

## Out of scope — machine access (important)

The social-login layer protects **human, browser-based** access only. The boundary is defined in
[ADR 0003](adr/0003-browser-and-machine-security-boundaries.md). Operationally:

- **Agents over raw MQTT (TCP 1883).** Robots / Raspberry Pis cannot do interactive OAuth.
  `config/mosquitto.conf` currently sets `allow_anonymous true`. For a public host, firewall 1883
  and switch the broker to username/password (or mTLS) credentials for agents. The browser's
  MQTT-over-WebSocket path (`/mqtt`) *is* covered by this auth layer.
- **MCP server (port 8001).** Intended for LLM clients, which also can't do interactive OAuth. The
  auth profile removes its host port; add a separately authenticated route only when needed.

## Consuming the identity in FastAPI (optional, future)

When auth is on, nginx forwards `X-Auth-Request-Email` / `X-Auth-Request-User` to the orchestrator
and the Compose profile sets `ANTIKYTHERA_TRUST_AUTH_HEADERS=true`. `/whoami` ignores those headers
in the normal/no-auth profile, preventing direct clients from fabricating a displayed identity.
