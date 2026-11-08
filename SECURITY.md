# Security Policy

## Our Approach

Initiative follows the principle of least privilege: every request should reach the minimum data its user is entitled to, and nothing else. Being built for small businesses, clubs, and community groups rather than enterprises makes that more important, not less — a committee's finances shouldn't be visible to the volunteers, and one group's data shouldn't be reachable from another group on the same server.

The rule we hold ourselves to is that **authorization is enforced in the database**, not only in application code. The app and the database agree on who can see what, and the database has the final say.

### Tenancy: a schema per guild

A guild is the tenancy boundary, and it is **structural**:

- Every guild's content — initiatives, projects, tasks, files, calendars, queues, counters, tags, comments — lives in its **own PostgreSQL schema** (`guild_<id>`), provisioned when the guild is created and dropped when it's deleted.
- Shared identity and configuration (users, guild memberships, invites, app settings, access grants, OIDC mappings) lives in `public`. **`public` holds no guild content on any install.**
- A request is routed into exactly one guild's schema with `SET ROLE`. The login role holds no standing access to any guild schema — the per-guild roles are granted `WITH INHERIT FALSE`, so a session must assume one explicitly and holds nothing until it does.

Cross-guild separation is therefore a property of which schema a query can address at all, rather than of a filter applied to tables shared between groups.

### The four gates

Every read or write of guild data passes the same nested checks, outermost first:

1. **Guild** — the schema boundary plus the per-request role above.
2. **Initiative** — within a guild, content of an initiative you're not a member of is not reachable. This is the hard isolation boundary between efforts in the same guild, enforced by row-level security.
3. **Initiative role** — which kinds of tools a member may use, and how.
4. **Per-item sharing (DAC)** — the final privilege gate on a specific project, file, or other tool instance.

Two deliberate overrides sit above them:

- **Guild administrators** have full read/write within their own guild, except content the platform holds.
- **Privileged access management (PAM)** — platform staff may be granted **time-bound, per-guild, audited** access. Never a standing bypass; see below.

One visible consequence: a guild member who isn't in an initiative receives **404, not 403**, for that initiative's content — row-level security hides the rows rather than reporting their existence.

### Row Level Security

- Guild content tables carry per-command policies that defer to a **single access function**, which asks whether the current user is a member of the initiative, a guild admin, or acting under a valid PAM grant.
- The application layer calls **the same function** for query-time filtering, so there is no parallel re-implementation to drift out of sync.
- Shared `public` tables carry role-scoped policies per platform tier plus own-row predicates.
- Tables use `FORCE ROW LEVEL SECURITY`, so even the role that owns them remains policy-bound for data access.

### Discretionary Access Control (DAC)

Within an initiative, teams decide who sees each individual item:

- **Read, write, and owner** levels, recorded in a single polymorphic `resource_grants` table.
- A grant's subject is **a user, an initiative role, or all initiative members** — so access can be handed to a whole role at once.
- Grants are scoped per resource: access to one project or file never implies access to another.

The same row-level security policies enforce DAC: each content policy checks the item's grants as well as the initiative boundary.

### Database roles

Initiative connects through **three PostgreSQL logins**, each least-privilege for its job:

| Role | Used for | Bypasses RLS? |
| --- | --- | --- |
| **`app_user`** | Every user-facing request | **No.** Assumes a scoped `guild_<id>` or `platform_<tier>` role per request |
| **`app_admin`** | Background jobs, startup seeding, bootstrapping endpoints | Yes — the standard Postgres trusted-batch actor, bounded by enumerated per-table `GRANT`s, and never serving a user request as itself. Entering a guild schema requires `SET ROLE`, which **drops** the bypass |
| **`app_provisioner`** | Migrations and DDL (`CREATE SCHEMA`, `CREATE ROLE`) | No — `NOSUPERUSER CREATEROLE`, and `FORCE ROW LEVEL SECURITY` keeps it policy-bound for data |

**The application never serves on a Postgres superuser connection.** The database owner's connection is opened at startup to create the three logins above, and closed before the app serves anything. A superuser (or `BYPASSRLS`) provisioning login **stops the boot**: every guarantee above is enforced by row-level security, and the provisioner is held to it. There is no opt-out.

### No standing bypass, and no superuser account

There is **no platform-wide superadmin** in Initiative, and no user-facing role bypasses row-level security.

Platform privileges are a five-rung ladder (`member → moderator → support → operator → owner`), each a real `platform_<tier>` Postgres role, with endpoints gated on **capabilities** rather than role names. Reaching a guild you don't belong to always requires an explicit, expiring, recorded grant:

- **moderator / support** — request access; an approver grants or denies; it auto-expires. Read-only by default.
- **operator / owner** — hold `data.bypass`, which is the right to **self-issue a break-glass grant** (created and self-approved in one step, short TTL, the row being the audit trail), not an ambient bypass. Removing the capability leaves no other route in.

Either way the session is routed through that guild's own roles and PAM context — never through a bypass.

### Authentication and secrets

- **HttpOnly `SameSite=Lax` cookie sessions** rather than `localStorage`, so the session isn't readable by scripts in the page. Native (Capacitor) apps store device tokens in secure platform storage.
- **A second layer under `SameSite` for cookie-authenticated writes.** An unsafe method authenticated by the session cookie must also arrive from an origin this deployment serves — `Sec-Fetch-Site: same-origin`, or an `Origin` on the CORS allowlist. Callers using an `Authorization` header — bearer tokens, API keys, device tokens — are unaffected, because a browser does not attach that header cross-site.
- **Passwords** are a minimum of 12 characters and are never stored in recoverable form.
- **OpenID Connect (OIDC) SSO** with PKCE, and optional claim-to-role mapping for guild and initiative membership.
- **Encryption at rest** for sensitive fields (AI provider keys, OIDC secrets, SMTP passwords, email addresses) using Fernet (AES-128-CBC) with a key derived from `SECRET_KEY`, with support for key rotation.
- **Minimal token scope** — tokens carry only what authentication needs; guild and role context is resolved server-side on every request.

### Extension surfaces

- **Marketplace widgets** run in an isolated sandbox with no capabilities, returning only a description of what to draw.
- **Personal API keys** can be minted read-only and pinned to a single guild, and are revoked by deletion or by a password reset.
- **The MCP server is off by default.** When enabled it is route-backed: every tool call runs through the real API as the key's user, under the same access rules as any other request.

When contributing, treat any path where a user could reach data outside their scope as a security issue, not a bug.

## Supported Versions

| Version | Supported |
| ------- | --------- |
| latest  | Yes       |

We recommend always running the latest release. This project hasn't reached a stable v1.0.0 yet, so only the latest version receives fixes.

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly. **Do not open a public GitHub issue.**

This address is for problems with **the Initiative software itself**. A problem with one particular server that runs it (a misconfiguration, an account someone else got into) goes to whoever runs that server: use **Report a security problem** in the app, or the address in the server's `/.well-known/security.txt`. Operators who receive a report about the software forward it here.

### How to Report

Email **security@beyonders.studio** with:

- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (optional)

### What to Expect

- Acknowledgment within 48 hours
- An estimated timeline for a fix
- Notification when the vulnerability is resolved
- Credit in the release notes (unless you prefer to remain anonymous)

## Scope

This policy covers:

- Backend API (`backend/`)
- Frontend SPA (`frontend/`)
- Docker configuration and deployment scripts
- GitHub Actions workflows

Third-party dependencies are out of scope, but we appreciate reports about vulnerable transitive dependencies.
