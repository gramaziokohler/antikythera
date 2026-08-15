# ADR 0003: Separate browser and machine security boundaries

- Status: Accepted
- Date: 2026-08-10

## Context

Browsers can complete an interactive OAuth flow and carry a secure session cookie. Robots,
Raspberry Pis, native agents, and MCP clients generally cannot. Treating all transports as if they
were browser requests either breaks machine clients or encourages bypasses around the edge proxy.

The base development Compose file publishes several service ports for convenience. Inheriting
those mappings in an authenticated deployment would let traffic bypass nginx.

## Decision

Browser and machine access use separate security boundaries:

- nginx is the sole browser ingress and protects the SPA, REST/SSE API, and same-origin `/mqtt`
  WebSocket route.
- The authenticated Compose overlay removes host mappings for Redis, MQTT WebSockets, FastAPI, and
  MCP.
- Raw MQTT remains available for external agents, but binds to loopback by default. An operator may
  bind it to a private or VPN interface only with broker credentials, mTLS, or an equivalent
  network restriction.
- MCP remains internal until a separate machine-authentication mechanism is selected.
- Browser identity is not translated into MQTT broker credentials or topic permissions.

## Consequences

- Browser traffic cannot bypass authentication through ports `8000` or `8083`.
- Remote agents need explicit network and broker configuration; social login is never presented as
  machine authentication.
- An authenticated browser collaborator still has the broker access granted by the shared browser
  MQTT path. Per-user topic ACLs are outside the current model.
- Deployments must decide independently how raw MQTT and MCP clients authenticate.

## Alternatives considered

- Expose every base Compose port and rely only on a host firewall: rejected as an unsafe default.
- Put raw MQTT or MCP behind interactive OAuth: rejected because their clients cannot reliably
  complete the browser flow.
- Issue per-user MQTT credentials from the social login: deferred because it couples broker ACLs,
  identity lifecycle, and agent credentials without a current requirement.
