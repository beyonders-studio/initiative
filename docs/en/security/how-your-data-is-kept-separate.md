---
icon: lucide/lock
---

# How your data is kept separate

Many communities can share one Initiative server, and each community's content is out of reach of the others. Inside a community, an initiative's content is out of reach of members who aren't in it. PostgreSQL enforces both on every request, with a schema for each community and row-level security inside it, so the boundaries hold in the database as well as in the application.

This page is for whoever has to check that: an IT team, an evaluator, somebody running a server. [Security & privacy](index.md) has the short version.

## Each community has its own schema

Every community's content lives in its own PostgreSQL schema. That holds its initiatives and everything in them: projects, tasks, documents, calendars, counters, posts, tags, comments and the rest of every tool's content. The schema is created with the community and dropped when the community is erased for good.

Accounts and server-wide settings live in the shared `public` schema: users, community memberships, invitations, server settings, access grants and sign-in provider settings. Direct messages are kept there too, as encrypted envelopes, because they belong to people rather than to a community (see [Private messages](private-messages.md)).

A request about a community is routed into that community's schema, and from there it can't name a table in any other community's schema. The separation comes from where the data is stored, so it doesn't rely on every query filtering correctly.

## Three database logins

Initiative connects to PostgreSQL through three logins, each holding only what its job needs.

| Login | What it does | Row-level security |
|---|---|---|
| `app_user` | Serves every request a person makes. | Always applies. The login has no access to any community's schema of its own. Each request switches into the role of one community, or of the person's platform rung (`platform_<tier>`), and is reset before the connection goes back to the pool. |
| `app_admin` | Runs background jobs and startup tasks, and the actions that have to happen before there's a membership to route through, such as creating a community or accepting an invitation. | Bypassed, but only on the shared tables it has been granted, one table at a time. To work in a community's schema it switches into that community's role, which gives up the bypass. |
| `app_provisioner` | Runs migrations, and creates or removes each community's schema and roles. | Applies. It owns the tables but isn't a superuser, and `FORCE ROW LEVEL SECURITY` holds the owner to the same policies as everyone else. |

Initiative never serves a request on a superuser connection. At startup it opens one connection as the database owner to create or check the three logins, and closes it before migrations run and before it serves anything. It refuses to start if the provisioning login is a superuser or can bypass row-level security. [Installation](../running-a-server/installation.md) covers how the logins are set up.

## Four gates and two overrides

Every read or write of a community's content passes four gates, outermost first:

| Gate | What it asks | Where it's enforced |
|---|---|---|
| 1. Community | Does this person belong to the community, or hold a live access grant to it? | The schema boundary and the role the request switches into. Membership or the grant is looked up again on every request. |
| 2. Initiative | Is this person a member of the initiative the content belongs to? | Row-level security on every table whose rows belong to an initiative. This is the hard boundary between groups inside one community. |
| 3. Initiative role | Does their role in that initiative let them use this tool, and how? | The same policies, from the role's permissions. |
| 4. Sharing | Has this item been shared with them, and at what level? | The same policies, from the item's grants. A grant can name one person, an initiative role, or every member of the initiative. |

Two overrides sit above the gates:

- **Community admins** can read and change everything in their own community, in every initiative, whatever its sharing. The exception is content the platform has put on hold, which reads as absent to everyone in the community, admins included.
- **Access grants** let platform staff reach a community they don't belong to. A grant covers one community, expires on its own and is recorded in the audit log. The request is routed through that community's own roles, so the policies apply to it like any other.

| Grant | What it allows |
|---|---|
| Read | Read everything in the community. |
| Read and write | Edit content that already exists. Creating content, managing members and changing permissions stay closed. |
| Moderate | Read everything, held content included, and change nothing. |

Moderators and support staff request a grant and an approver grants or denies it. Platform operators and owners can issue themselves a short break-glass grant in one step, and the grant itself is the record. No grant makes its holder a community admin. [Platform roles](../running-a-server/platform-roles.md) covers who can do what.

A member of a community who isn't in an initiative gets **404 Not Found** for that initiative's content. Row-level security hides the rows, so the server answers as if they weren't there.

??? techspec "How the policies decide"
    Gates 2 to 4 are PostgreSQL row-level security policies on the community's content tables. Each policy defers to one function in the community's own schema, `initiative_access()`, which admits a member of the initiative, a community admin, a live access grant, or the system login. Sharing is checked by `resource_access()` in the same policies.

    The facts those functions read (which initiatives the person is in, their roles, whether they're a community admin, any live grant) are computed by the database at the start of each request, in that community's schema, from the membership and grant rows as they stand. Revoking a grant or a membership changes the next request's answer with nothing else to update.

    Initiative's own query filters call the same function, so the application and the database give the same answer, and the database has the final say.

## Sign-in and sessions

| What | How |
|---|---|
| Browser session | A cookie named `session_token`: `HttpOnly`, `SameSite=Lax`, and `Secure` when `APP_URL` starts with `https`. It lasts `AUTH_ACCESS_TTL_MINUTES` (15 by default) and is renewed while you use the app. |
| Renewal | A `refresh_token` cookie with the same flags, sent only to `/api/v1/auth`. A session ends after `AUTH_REFRESH_TTL_DAYS` (30 by default) without use. |
| Changes made with the cookie | Must come from a page this deployment serves: `Sec-Fetch-Site: same-origin`, or an `Origin` on the CORS allowlist. Requests that carry an `Authorization` header, such as API keys and the apps, aren't affected. |
| Phone and desktop apps | Keep their sign-in in the app's own storage (Capacitor Preferences), in a separate group that Android backups leave out. |
| What a token carries | Who you are. Your communities, roles and grants are looked up again on each request, so a change applies to your next request. |
| Single sign-on | OpenID Connect, with PKCE (`S256`). |
| Passwords | At least 12 characters, checked against known breaches while that check is on (it is by default), and stored only as a one-way hash. The breach check sends only the first 5 characters of the password's SHA-1 hash. |

## Encryption

- **In transit.** Initiative expects to be served over HTTPS, by the server or a proxy in front of it. When `APP_URL` starts with `https`, it marks its cookies `Secure` and sends `Strict-Transport-Security`. See [Configuration](../running-a-server/configuration.md).
- **Sensitive fields at rest.** Encrypted with Fernet, using a separate key for each kind of field, each derived from `SECRET_KEY` with HKDF-SHA256. Email addresses are also kept as a keyed hash, so an address can be looked up without decrypting every row. Set `PREVIOUS_SECRET_KEY` beside a new `SECRET_KEY` and Initiative re-encrypts all of them at startup.
- **Stored files.** Encrypted when `STORAGE_ENCRYPTION` is set, and off by default. See [Encrypting stored files](../running-a-server/object-storage.md#encrypting-stored-files).
- **Direct messages.** End-to-end encrypted. See [Private messages](private-messages.md).

The encrypted fields:

- email addresses and dates of birth
- authenticator-app (TOTP) seeds
- AI provider keys
- single sign-on client secrets, and the refresh tokens providers issue
- the email server password, the S3 secret key, the captcha secret, the Firebase service account and the push relay key
- plug-in settings, plug-in vendor secrets and the plug-in platform's signing key
- the credentials an import uses
- notes on held content, and the text of moderation removals
- community storage keys

## Related

- [Security & privacy](index.md): the short version.
- [Data & compliance](data-and-compliance.md): what's kept, what leaves the server, and your rights over it.
- [Sharing & access](../sharing/index.md): how you set the initiative and item layers yourself.
