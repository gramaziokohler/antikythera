# ADR 0002: Lightweight collaborator authorization

- Status: Accepted
- Date: 2026-08-10

## Context

Authentication establishes identity but does not determine what an authenticated person may do.
Current Antikythera deployments are small collaborative environments whose users work on shared
blueprints, models, and execution sessions. A general policy engine, per-resource ownership model,
or enterprise role hierarchy would add substantial complexity before a concrete separation need
exists.

At the same time, successful social login alone must not grant access to an internet-facing
instance.

## Decision

The initial authorization model has one application role: **collaborator**.

- An authenticated email must match the explicit email allowlist or an operator-configured email
  domain.
- Every collaborator can currently see and operate all shared blueprints, models, and sessions.
- Per-resource ownership, organization hierarchies, and a general policy engine are deferred.
- If coarse separation becomes necessary, the next increment will be two roles—`member` and
  `admin`—with admin checks limited to destructive or global operations.

The domain allowlist and explicit email file are additive. A wildcard email domain is prohibited
for restricted deployments because it turns successful social login into universal access.

## Consequences

- Authorization remains understandable and editable by a small deployment operator.
- Existing collaborative workflows do not acquire ownership or sharing mechanics.
- All collaborators are effectively trusted operators until a second role is introduced.
- Audit or ownership requirements will require a later ADR and data-model changes; the forwarded
  identity alone does not provide those semantics.

## Alternatives considered

- Full RBAC/ABAC at introduction: deferred because there is no stable permission taxonomy yet.
- GitHub-only organization/team membership: rejected as the universal model because Google and
  future institutional OIDC identities must work through the same boundary.
- Authentication without an allowlist: rejected for public deployments.
