---
icon: lucide/shield-check
---

# Security & privacy

In Initiative, the people who can see something are the people it was shared with. The database checks that on every request, so it holds without anybody having to set it up.

This section explains how. Pick the page that answers your question:

| If you want to know | Read |
|---|---|
| How communities are kept apart, and how an initiative stays private inside its community | [How your data is kept separate](how-your-data-is-kept-separate.md) |
| What end-to-end encryption covers in direct messages, and what the server can see | [Private messages](private-messages.md) |
| What Initiative keeps, where it lives, what leaves the server, and how to export or erase it | [Data & compliance](data-and-compliance.md) |
| How a community can require its own single sign-on, a second factor or shorter sessions | [Your community's sign-in and security](community-security.md) |
| Where to report a security problem | [Reporting a problem](reporting-a-problem.md) |

## What you can rely on

- **Each community is separate.** Its content lives in its own part of the database, and members of other communities on the same server can't reach it.
- **An initiative is private to its members.** Inside a community, somebody who isn't in an initiative can't open anything in it unless an item was shared with them. The community's admins can see everything in their community. See [Sharing & access](../sharing/index.md).
- **Direct messages are end-to-end encrypted.** Only the devices in the conversation hold the keys to read them.
- **Your sign-in is protected.** Your session is kept in a cookie the page's own scripts can't read, and passwords are at least 12 characters and stored only as a one-way hash. You can add [two-factor authentication](../account/two-factor-authentication.md) or a [passkey](../account/passkeys.md).
- **Staff access is temporary and recorded.** Somebody who helps run the server can open a community they don't belong to only through a grant that expires, and every grant is recorded in the audit log.

## Looking after your account

- **My Settings → Security** shows everywhere you're signed in, and you can sign out any browser or device you don't recognize there.
- Every email about a change to how you sign in has a **This wasn't me** button. It signs your account out everywhere and turns off your API keys. See [Sign-in and security](../account/sign-in-and-security.md#this-wasnt-me).
- If an [API key](../account/api-keys-and-integrations.md) might have been seen by somebody else, delete it.
- You can deactivate or delete your account from **My Settings → Account**. [Removing data](data-and-compliance.md#removing-data) explains what each one does.

## If you run the server

How the server is set up and looked after matters too: its secret key, HTTPS, backups and updates. The [server guide](../running-a-server/index.md) covers it, starting with [Configuration](../running-a-server/configuration.md) and [Backups & updates](../running-a-server/backups-and-updates.md).
