# ADR 0004: Server-side sessions and file-backed secrets

- Status: Accepted
- Date: 2026-08-10

## Context

OIDC sessions can contain tokens large enough to exceed practical browser-cookie and nginx header
limits. Authenticated deployments also require an oauth2-proxy client secret, cookie-encryption
material, and Google/GitHub client secrets. Supplying these values directly through Compose
environment variables makes accidental disclosure through rendered configuration and process
inspection more likely.

Federated logout is not uniform: clearing Antikythera's session does not guarantee that Google or
GitHub has ended its own session.

## Decision

- oauth2-proxy stores session data in Redis database 1 and places only a small session reference in
  the browser cookie.
- The default local session lasts 12 hours and refreshes after one hour; deployments may override
  both values.
- nginx propagates refreshed cookies returned by oauth2-proxy auth subrequests.
- Sensitive oauth2-proxy and provider credentials are mounted as Compose secret files.
- `dex-init` reads those files, validates required provider settings, and refuses to render a
  partial Dex configuration.
- Logout ends the Antikythera/oauth2-proxy session and lands on a public signed-out page. It states
  explicitly that the upstream provider session is unchanged.

## Consequences

- Session cookies remain small and token refresh works with nginx `auth_request`.
- Redis becomes part of the authentication session path; its unavailability prevents session
  validation.
- Production credentials no longer appear as literal Compose environment values, although Dex's
  rendered configuration necessarily contains the client secrets inside its protected volume.
- Operators must recreate `dex-init` and Dex after rotating provider or client credentials.
- “Sign out” is local logout, not guaranteed federated single logout.

## Alternatives considered

- Store the complete session in encrypted browser cookies: rejected because OIDC token size and
  split-cookie handling make the nginx integration more fragile.
- Put secrets directly in `.env.auth`: rejected for production credentials.
- Claim complete provider logout: rejected because Dex cannot expose one reliable logout operation
  across all configured social providers.
