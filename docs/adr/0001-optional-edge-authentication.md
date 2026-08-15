# ADR 0001: Optional edge authentication

- Status: Accepted
- Date: 2026-08-10

## Context

Antikythera must remain easy to run without identity infrastructure on a developer machine or a
trusted fabrication network. Internet-facing instances need human authentication, multiple social
identity providers, and a single security boundary across the SPA, REST/SSE API, and browser MQTT
connection. Maintaining passwords inside Antikythera would add credential-recovery, storage, and
security responsibilities that are unrelated to orchestration.

Authentication inside every application surface would also duplicate protocol handling and make
the unauthenticated development mode harder to preserve.

## Decision

Human authentication is an optional Compose overlay enforced at nginx:

1. nginx calls oauth2-proxy through `auth_request` for every browser-facing route.
2. oauth2-proxy owns the Antikythera session and authorization allowlist.
3. Dex is the OIDC broker between oauth2-proxy and Google/GitHub. Additional OIDC connectors may
   be added later.
4. Antikythera does not implement passwords or validate OAuth tokens in FastAPI.
5. The application may consume identity headers only when the auth profile explicitly enables
   trust in the edge proxy.
6. Authentication remains disabled when the overlay is not selected.

Browser document requests redirect into OAuth. API and WebSocket requests retain `401` semantics
so programmatic clients never receive a sign-in HTML document in place of JSON or an Upgrade
response.

## Consequences

- One login protects the UI, REST, SSE, and MQTT-over-WebSocket surfaces.
- The default local/trusted-network workflow remains unchanged.
- nginx becomes the mandatory browser ingress for authenticated deployments; direct backend ports
  must not be published.
- Deployments that do not use Compose must reproduce the same edge boundary using their native
  service manager and reverse proxy.
- Dex and oauth2-proxy add operational dependencies, but Antikythera avoids owning user passwords
  or provider-specific OAuth implementations.

## Alternatives considered

- Application-level OAuth middleware in FastAPI: rejected because it would not protect static
  files or MQTT WebSockets and would couple the no-auth mode to application authorization code.
- A separate oauth2-proxy instance per provider: rejected because it fragments the login and
  session boundary.
- Native username/password accounts: rejected because Antikythera should not become a credential
  authority.
