---
icon: lucide/key-round
---

# Your community's sign-in and security

Most communities never need this page. A club, a committee, a group running a campaign — everybody signs in the ordinary way, and that is the end of it.

Some communities answer to somebody: a business with an IT department, a chapter with a parent organisation, a team that filled in a security questionnaire before it was allowed to use anything at all. For those, **Community settings → Security** decides two things — **who gets in**, and **on what terms**.

Only a community's [superadmin](../guides/communities.md#why-superadmin-is-separate) reaches that tab; an ordinary admin does not see it. Whoever runs the server grants it per community as two independent switches — one for sign-in, one for the security standard — and with neither there is no tab.

## Who gets in

### Which sign-ins are yours

Whoever runs the server registers the identity providers. Your community says **which of them count as yours**, and **whose accounts on them do**.

That second half is the point. A provider like Google vouches for anybody with an account, so a community connecting to one names the accounts that are its own:

| You use | Narrow it by | Values look like |
|---|---|---|
| Google Workspace | Workspace domain | `example.com` |
| Microsoft Entra | Entra tenant | your tenant id |
| Your own identity provider | nothing — it already holds only your people | — |

It is both halves or neither, and any one value is enough to count. You never handle an issuer, a client id or a secret: a community connects to a provider, it does not configure one.

**Joining on arrival** is a switch on the connection. Leave it off and you invite people yourself. Turn it on and anybody who counts as yours becomes a member when they sign in, once the server's operators have agreed that the domain or tenant you named is yours. Those are ordinary memberships — turning the switch back off, or disconnecting, removes nobody.

**The member sign-in link** offers your community's providers and lands people inside it rather than at the front door. It is a link, not an invite — it grants nothing on its own and never expires.

### Where your people land

If your provider reports which groups somebody is in, **rules** say what those groups mean here. A rule names one group and gives it a standing: member or admin of the community, and optionally a place in one initiative with a role there. So `eng-platform` arrives in the Platform initiative and `ops-leads` arrives as community admins, without anybody clicking anything.

- Rules match the group **exactly** as your provider spells it, give or take capitals.
- Rules apply only to people your connection counts as yours — the accounts it narrows the provider to. Somebody from another workspace on the same provider, in a group with the same name, is not placed here. Leave your workspace and the next sign-in releases what the rules gave you.
- A rule grants **member or admin** — never the superadmin seat.
- Standing is reconciled at **each sign-in** through that provider. Take a group away and the next sign-in takes the standing with it.
- Memberships given by hand are never touched, and deleting a rule revokes nothing by itself — the next sign-in does.

Where your community has [custom roles](../guides/communities.md#custom-roles), **Custom roles by group** gives one to whoever signs in carrying a group. Those rules are read in order, and the first group a sign-in carries decides the role. Like the rules above, they apply only to people your connection counts as yours, are reconciled at each sign-in, and leave a role somebody gave by hand alone.

**Rules set by the deployment.** Your server's operators can write rules on a provider too. They place people here when your connection to that provider has **Let the deployment place people from this provider** switched on, or when the server applies its rules to every community. They're listed beside your own, read-only, and marked when they're not applying.

!!! warning "An empty answer is still an answer"
    A provider asked for groups that reports none matches no rules, and the standings those rules granted are released. That is different from a provider nobody has told where its groups live: there, rules never run at all, and the tab marks the provider so you can see why nothing matches.

### The sign-in requirement

By default a community is **open**: any signed-in member reaches it.

Instead you can **require single sign-on** — through any provider of yours, or one you name. Signing in elsewhere on the same server does not count. Independently of that, you can ask that the session carried a **second factor** or a **passkey**.

The requirement is checked when somebody enters the community and again in the database, so it holds for every route in rather than only the sign-in page.

You have to satisfy a requirement yourself before you can set it; the page names the part your session is missing and offers to settle it there and then. Where the server already asks everybody for a second factor, that box is not offered — your answer is kept, and returns if the server relaxes.

## On what terms

### API access

[Personal API keys](../account/api-keys-and-integrations.md) are how members reach Initiative from scripts, integrations and MCP clients. Your community decides whether they work **here**.

Every member's keys work here by default. To stop one person's, use the **API access** switch beside them in **Community settings → Users**. Only a superadmin sees that column, and only while the server grants this community the security standard.

Turn it off and none of that person's keys reach this community, including keys that already exist. Those keys carry on working for their other communities — the decision is about your space, not somebody's account. Nothing is revoked, so turning it back on restores them.

### Session length

**Sign in again every twelve hours** holds your members to that instead of the server's ordinary session length.

Twelve, rather than a number you pick: somebody in two communities that both ask for this gets one answer instead of a comparison. Shorter still wins, so a server that signs people out sooner keeps doing that.

The same switch also ends a session that is **left alone for fifteen minutes**, or sooner if the server sets a shorter idle window of its own. Twelve hours is the longest a session may last; fifteen minutes is the longest it may sit untouched. Both are needed to meet the automatic-logoff expectations these communities are usually holding themselves to, and both come from the one switch rather than two.

Touching it means the person: a tap, a click, typing or scrolling. The app renews its own session while somebody is using it, so the fifteen minutes only run down once they stop, and an app left open on a screen nobody touches does not keep itself signed in. What they see when they come back is the sign-in page.

It follows the person rather than the room, so it applies to your members everywhere they go, in a browser and in the apps alike. The fifteen minutes take hold the next time the app renews somebody's session. The twelve hours take hold at their next sign-in, so nobody is cut off mid-sentence.

### What notifications carry

Three switches decide what leaves the app about this community: whether notifications may reach **phones**, whether they may reach **mailboxes**, and whether what they say may **name the thing it is about**.

Whoever runs the server answers the same three questions for every community. **The stricter answer applies**, so a community can be quieter than its server but never louder. Where the server has already switched something off, the community's switch says so and has nothing to decide.

With details hidden, a push or an email reads *"You were mentioned in a comment"* and the app is where the rest of it is. The bell inside the app always shows everything — these settings govern what travels, not what members see here.

Sign-in codes, address confirmations, password resets and notices about somebody's own account are not notifications. They belong to the account rather than to the community, and they are sent either way.

Members keep their own [notification settings](../guides/notifications.md) underneath all of this. These switches are a ceiling, not a default: they can make a channel unavailable, never turn one on for somebody who asked for silence.

### Ranking search by engagement

**Rank search results by community engagement** puts what more members have recently opened or worked on a little higher in search, the command palette and pickers. It reorders results; it never adds one.

What is kept is a rough level for each item, worked out once an hour from the last week of opens and changes in this community. An item gets a level only once three different people have engaged with it. The level names nobody and holds no count, and it is read only beside items the reader can already open. See [Data & compliance](data-and-compliance.md#what-initiative-keeps-about-use).

Turn it off and the levels are deleted within the hour; results go back to being ordered by the match alone. Whoever runs the server can turn it off for every community, and then this switch says so and has nothing to decide. Each member can also leave their own activity out, under **My Settings → Privacy**.

## Turning something off

Nothing here destroys anything on the way out.

| If you | Then |
|---|---|
| **Disconnect a provider** | Its button comes off your sign-in page and nobody new arrives through it. Nobody is signed out, no account changes, no membership is removed. If a requirement rests on it, you are asked to lift that first. |
| **Lift a requirement** | Members simply stop being asked. |
| **Turn somebody's API access back on** | The keys they already had reach you again, with nobody minting replacements. |
| **Stop asking for twelve-hour sessions** | People stop being timed out for idleness the next time the app renews their session, and return to the ordinary length at their next sign-in. A session already held to twelve hours keeps that limit until it ends. |
| **Allow mobile notifications again** | Phones receive this community's notifications again, from the next one sent. |
| **Stop hiding notification details** | The next notification to leave names what it is about. Ones already sent are not revisited. |
| **Rank by engagement again** | Levels are worked out again at the next hourly pass, from the opens and changes of the past week. |

If whoever runs your server withdraws one of the two switches, that half of the tab closes and nothing else happens: your connections stay, your members keep signing in, nobody is ejected or unlinked, and **a requirement you already set stays in force**. What closed is your ability to change the setup, not the setup — so changing it after that means asking for the switch back.

??? techspec "For the technically minded — what each control actually is"

    **Connections** are rows joining your community to a provider in the server's registry, optionally narrowed by a claim and the values that count — `hd` for a Google Workspace domain, `tid` for an Entra tenant. Matching is case-insensitive and any-one-of. The values your session asserted are recorded when you sign in; *which* values count is read live, so editing a narrowing lands without waiting for anybody to sign in again.

    **Rules** map one group value, per provider, to a community role and optionally an initiative and a role in it. They reconcile in both directions at each sign-in through that provider: granting what they match, and releasing only what that same provider's earlier syncs granted.

    **Custom role rules** map one group value, per provider, to a custom role. They are stored in the community's own schema, beside the roles, and read in order: the first match wins. An assignment records the provider that gave it, so a later sign-in through that provider changes or releases only its own.

    **The requirement** is one row per community: `open`, or `required` naming a provider and/or the methods a session must carry (`sso`, `totp`, `passkey`). `password` is refused by a database constraint — whether passwords exist at all is the server's question, not a community's. It is enforced at the community-context gate, which answers with a step-up challenge, and again inside the database's row-level security.

    **Notification delivery** is three booleans on the community, each read alongside the platform's own where a notification is sent rather than at the moment either is saved, so tightening the server's answer covers every community at once and no community row is rewritten. Redaction is applied to the message as it is built for the channel it leaves on; the stored notification the bell reads is unaffected. A community switching mobile notifications off stops its own sends — the device registrations themselves belong to the account, not to any one community, so they stay.

    **Engagement ranking** is a flag on the community, read with the server's own by the hourly pass. Each person counts once per item, at their weightiest engagement (an open counts 1, half that when it came from search, and a change 2), halving every two days over a seven-day window. An item needs three different people before it has a level, which is `floor(log2(1 + score))`, capped at 7. A search match's rank is multiplied by `1 + 0.1 × level`. Levels sit in each community's own schema and are read through the same per-item gate as the item; plug-ins can't read them.

    **API access** is a flag on each membership, read by the community-context gate on every request made with a personal key, so a key is judged when it is used, not when it is created. **Session length** is a flag on the community itself rather than on the policy row, which is why it outlives a requirement being lifted. The session standard is twelve hours, `min()`-ed with the server's own limit; sessions come under it at their next sign-in, in a browser and in the apps alike. The idle standard is fifteen minutes, carried by the session's own two clocks rather than checked per request: the refresh row expires that far out and each renewal reads the window again and re-stamps it from the person's last input, which the client reports as `idle_seconds`, and the access token is minted no longer-lived than the row it names. So an idle session lapses on its own, and the control costs one sign-in rather than a database read on every call.

## Related

- [Working with communities](../guides/communities.md) — the rest of the settings tabs, and what the superadmin seat is for.
- [Single sign-on](../running-a-server/single-sign-on.md) — for whoever runs the server and registers the providers.
- [API keys & integrations](../account/api-keys-and-integrations.md) — what a personal key is, from a member's side.
- [Two-factor authentication](../account/two-factor-authentication.md) and [Passkeys](../account/passkeys.md) — what you are asking members for.
