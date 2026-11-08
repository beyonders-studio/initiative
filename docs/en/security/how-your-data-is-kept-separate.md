---
icon: lucide/lock
---

# How your data is kept separate

This page is the **technical explanation** of Initiative's multi-tenancy and access control — written for project managers, people who run servers, IT teams, and anyone evaluating Initiative for a group that cares about data isolation. It avoids code, but it doesn't shy away from detail.

If you just want the everyday version, read [Security & privacy](index.md) instead.

## The short version

Initiative is **multi-tenant**: many separate groups (communities) share one server without ever seeing each other's data. The separation is enforced **in the database itself**, not only in the application, so the database is the final authority on what any request may return. Security is **fail-closed**: the default is no access, and access has to be positively established on every request.

## Each community gets its own space in the database

A community is not just a label attached to shared rows. Each community's content — its initiatives, projects, tasks, files, calendar, counters, posts, tags, and comments — lives in its **own dedicated area of the database** (a separate schema), provisioned when the community is created and removed when the community is deleted.

Shared identity and configuration (the list of users, community memberships, invitations, server settings) lives in a common area. Everything that *belongs to a community* lives in that community's own space.

??? techspec "Why a separate schema per community, rather than a shared table with a community column?"
    Because it makes the boundary structural rather than conditional. A request is routed into one community's space and literally cannot address another community's tables — the separation is a property of where the data sits, not of the queries written against it. That's a stronger isolation line, and it's what groups with real confidentiality requirements are asking about. This is a firm architectural commitment, not an implementation detail that might change.

## The database connects under least-privilege roles

The application **never connects to the database as a superuser** — not for requests, not for jobs, not even for migrations. It uses purpose-built database roles, each with the least privilege it needs:

| Role | Used for | Can it bypass security rules? |
|---|---|---|
| Application role | Every normal user request | **No** — security rules always apply |
| System role | Background jobs, startup tasks | Yes, but never on a user request — and only on the specific tables it has been explicitly granted |
| Provisioning role | Migrations, creating/removing community spaces | Structure only — it owns the tables but its own data access still obeys the security rules |

The key point: the role that handles your requests **cannot bypass the security rules**. Each request temporarily assumes the specific community role it's allowed to, does its work, and resets. There is no standing, all-communities back door in the request path.

## The gates

Every read or write of community data passes through the same access model: four nested gates you clear from the outside in, plus two deliberate overrides above them.

```mermaid
graph TD
  A["1 · Community<br/>member of this group?"] --> B["2 · Initiative<br/>part of this effort?"]
  B --> C["3 · Initiative role<br/>allowed to use this tool?"]
  C --> D["4 · Item sharing<br/>shared with you (view/edit/own)?"]
  D --> OK["✅ Access granted"]
  E["Community admin<br/>(full access in own community)"] -.override.-> OK
  F["Time-bound support grant<br/>(audited, expiring)"] -.override.-> OK
```

1. **Community** — no community data exists for you unless you belong to the community. This is the outer wall.
2. **Initiative** — within a community, you can't reach the content of an initiative you're not a member of. This is the hard isolation boundary that keeps sensitive efforts away from non-involved members of the *same* community.
3. **Initiative role** — your role decides which *kinds* of tools you may use, and how.
4. **Item sharing** — for a specific project or file, per-item grants decide whether you can view, edit, or own it.

Two deliberate overrides sit above the four gates:

- **Community administrators** always have full read/write access within their own community. Running a group requires it.
- **Support access** for hosted operators is **time-bound, scoped to one community, and recorded** — granted explicitly and expiring automatically. It is never a permanent or ambient bypass.

??? techspec "How the gates are actually enforced"
    Gates 2–4 are implemented with PostgreSQL **row-level security** policies attached to the community content tables. Each policy defers to a single access function that asks: is the current user a member of this initiative, **or** a community admin, **or** acting under a valid support grant? Because the check lives in the database and runs on every statement, the application and the database agree on the answer — and the database has the final say. Gate 1 (community) is the schema boundary plus the per-request role described above. A consequence worth knowing: a community member who isn't in a given initiative gets a "not found" result for that initiative's content, because row-level security hides the rows entirely.

## Sessions and sign-in

- **Web sessions** use secure, HttpOnly cookies, so the session is held by the browser rather than exposed to page scripts.
- **Mobile apps** store their credentials in the device's secure storage.
- **Single sign-on (OIDC)** is supported, with modern protections (PKCE) and optional automatic mapping of identity-provider groups to community and initiative memberships.
- **Sign-in tokens carry the minimum** needed; your community and role context is worked out fresh, server-side, on each request — so a stale token can't grant access you no longer have.

## Encryption

- **In transit:** you should always run Initiative behind HTTPS, so traffic between browser and server is encrypted. (Running the server? See [Configuration](../running-a-server/configuration.md).)
- **At rest:** the most sensitive stored fields — saved AI provider keys, single-sign-on secrets, email server passwords, and email addresses — are **encrypted** in the database using a key derived from the server's secret, so they aren't readable from the raw data alone.

## What this means in practice

- One server can safely host many unrelated groups.
- The database boundary holds on its own terms, independently of the application — so the isolation between groups is a property of where the data lives, not of every feature being written correctly.
- "Who can see this?" has one consistent answer, enforced everywhere. The web app, the mobile app, file downloads and live collaboration all defer to the same gates.

## Related

- [Security & privacy](index.md) — the plain-language version.
- [Data & compliance](data-and-compliance.md) — data ownership, your rights, and compliance posture.
- [Sharing & access](../sharing/index.md) — how you set the initiative and item layers yourself.
