---
icon: lucide/key-round
---

# Your community's sign-in and security

Most communities never need this page, because everybody signs in the ordinary way. Some answer to an IT department, a parent organization or an auditor. For them, the **Security** tab in **Community Settings** decides how members sign in and what terms they're held to.

## Who can change these settings

Only the community's [superadmin](../guides/communities.md) sees the **Security** tab. An ordinary community admin doesn't.

Whoever runs the server decides which half of the tab a community gets. A platform operator or owner opens **Operator Dashboard → Communities**, selects **Manage** beside the community, and turns on either option under **What it decides for itself**:

| Option | What it opens |
|---|---|
| **Its own sign-in** | **Sign-in providers**, **Group rules**, and the **Members** and **Guests** sign-in requirements. |
| **Its own security standard** | **Second factor**, **Sign in again every 12 hours**, **Longest guest stay**, the **Privacy** switches, and the **API access** column in **Users**. |

With neither option, the tab doesn't appear. The **Guests** and **Longest guest stay** rows appear only while the community can have guests, and **Second factor** only while the server offers one.

## Connect your sign-in provider

Whoever runs the server registers the identity providers (see [Single sign-on](../running-a-server/single-sign-on.md)). A community connects to one of them and says whose accounts on it count as its own. A connection that doesn't say admits nobody, because a provider such as Google vouches for anybody who has an account there.

| Whose accounts count as yours | Claim it reads | Values look like |
|---|---|---|
| **Google Workspace domain** | `hd` | `example.com` |
| **Microsoft Entra tenant** | `tid` | your tenant ID |
| **Group membership** | `groups` | a group name |
| **Domain** | `domain` | `example.com` |
| **Another claim…** | a claim you name | its values |

Matching ignores capitals, and any one value is enough. You never handle an issuer, a client ID or a secret: those belong to the server's registration of the provider.

To connect a provider:

1. Open **Community Settings** and select the **Security** tab.
2. Select **Connect a provider**, or **Set up sign-in** if nothing is connected yet.
3. Under **Which way in**, pick the provider your members already sign in with.
4. Under **Whose people**, choose an option in **Whose accounts count as yours**, type the **Values that count**, and select **Next**.
5. Under **Where they land**, turn on **Join them to this community** if people who count as yours should join when they first sign in.
6. Optionally, fill in **A first group** and choose what its people join as.
7. If the wizard asks **Do we insist**, tick **Require members to arrive through this provider** to make it the only way in.
8. Select **Connect provider**.

The provider's button appears on your community's sign-in page. Nobody already in the community is signed out.

**Join them to this community** waits until whoever runs the server agrees that the domain or tenant you named is yours. Until then, the connection admits people who match, and they join by invitation. The memberships it creates are ordinary ones, so turning the switch off or disconnecting the provider removes nobody.

**Member sign-in link** is an address that offers your providers and brings people straight into the community. It grants nothing on its own and doesn't expire.

A connection marked **From your server** is the server's default for that provider, and applies until you select **Make it ours**, which makes it a connection of your own to edit. **Join them to this community** is never part of a default. **Turn off** pauses a connection of your own, and **Turn on** resumes it.

## Where your people land

If your provider reports which groups somebody is in, group rules say what those groups mean here. A rule names one group and says whether its people join as a member or an admin of the community, and optionally which initiative they start in and with what role. So `eng-platform` can arrive in the Platform initiative and `ops-leads` as community admins, with nobody clicking anything.

To add a rule:

1. Open **Community Settings** and select the **Security** tab.
2. Under **Group rules**, beside **Where people land**, select **Add**.
3. Choose the **Provider**, and type the **Group** exactly as your provider spells it.
4. Under **They join as**, choose **a member** or **an admin**.
5. To start them in an initiative, choose it under **And start in**, then choose a role under **In that initiative, as**.
6. Select **Add a rule**.

The rule takes hold the next time somebody in that group signs in through that provider.

- A rule matches the group exactly as the provider spells it, ignoring capitals.
- A rule gives **a member** or **an admin**, never the superadmin seat.
- Rules apply only to people the connection counts as yours. Somebody from another workspace on the same provider, in a group with the same name, isn't placed here.
- Rules are checked at each sign-in through that provider, and about every 15 minutes in the background for accounts whose provider gave Initiative a refresh token. Lose the group and the next check takes away what the rule gave.
- A rule releases only what it gave. Memberships and roles somebody gave by hand are left alone, and so is the superadmin seat.
- Removing a rule takes nothing away by itself. People lose what it gave at their next check.

**Custom roles · the first match decides** gives a [custom role](../guides/communities.md) to whoever signs in carrying a group. Select **Add role rule**, choose the provider, the group and the **Custom role**, and save. These rules are read from the top, and the first rule whose group the person carries decides the role, so use the arrows to put the more specific groups first. They follow the same checks as the rules above, and a role somebody gave by hand stays theirs.

**Rules from your server.** Whoever runs the server can write group rules for a provider that name your community. They place people here beside your own rules once your connection to that provider has **Let your server place people** ticked in its menu, or when the server applies its rules to every community. They're listed under your own, read-only, and marked when they aren't applying.

!!! warning "A provider that reports no groups"
    A provider that sends a groups list with none of your groups in it matches no rules, and the next check releases what rules gave that person. A provider the server hasn't told where to find groups never runs the rules at all. Those rules show **No groups reported**.

## The sign-in requirement

**Members** under **Sign-in rules** says what members need before they can open the community:

- **Any signed-in account**, the default: members sign in however the server allows.
- **Through our providers**: only a sign-in through the provider you pick counts, or through **Any of our sign-in providers**. Signing in some other way on the same server doesn't count.
- **Also require a passkey**: members must have signed in with a passkey, or presented one, in the current session.

To require your provider:

1. Open **Community Settings** and select the **Security** tab.
2. Under **Sign-in rules**, select **Change** beside **Members**.
3. Choose **Through our providers**, then pick a provider or **Any of our sign-in providers**.
4. To ask for a passkey too, tick **Also require a passkey**.
5. Read **When you save**, which counts the members who haven't signed in that way yet.
6. Select **Save requirement**.

You have to meet a requirement yourself before you can save it. If your session hasn't used that provider or a passkey, the dialog says so and lets you do it there. Nobody is signed out when you save. Members who came in another way are asked the next time they open the community.

**Guests** takes the same choices for [guests](../sharing/guests.md). You don't have to meet the guests' requirement yourself.

The requirement is checked when somebody opens the community, which asks them to sign in the right way if they haven't, and again by the database on every request.

## Second factor

**Second factor** set to **Required in each session** means everybody who opens the community, guests included, presents an authenticator code or a passkey in each session. They can add one without signing out. You need one of your own before you can turn it on.

Where the server already asks every account for a second factor, the row shows **Set by your server**. Your own answer is kept, and applies again if the server stops asking.

## Session length

**Sign in again every 12 hours** holds your members to a session of at most 12 hours. If the server's own limit is shorter, the shorter one applies.

The same switch ends a session nobody has touched for 15 minutes, or sooner if the server sets a shorter idle limit. A tap, a click, a key press or a scroll counts, and so does bringing the app back into view. The app renews its session while somebody is using it, so the 15 minutes run only once they stop. When they come back, they see the sign-in page.

It follows the person, so it applies to your members in every community on the server, in a browser and in the apps. The idle limit takes hold the next time the app renews somebody's session, and the 12 hours at their next sign-in.

To turn it on:

1. Open **Community Settings** and select the **Security** tab.
2. Under **Sign-in rules**, select **Change** beside **Sign in again every 12 hours**.
3. Choose **Sign in again every 12 hours**.
4. Select **Save**.

## API access

[Personal API keys](../account/api-keys-and-integrations.md) are how members reach Initiative from scripts, integrations and MCP clients. Every member's keys work in your community until you turn them off for that person.

To stop one person's keys reaching your community:

1. Open **Community Settings** and select the **Users** tab.
2. Find the person, and turn off their switch in the **API access** column.

None of that person's keys reach your community after that, including keys they already have. Their keys keep working in their other communities, and nothing is revoked, so turning the switch back on restores them. Only a superadmin sees the column, and only while the community has its own security standard.

## Longest guest stay

**Longest guest stay** caps how long a guest invitation or extension can run, in days. Guests already in the community keep their end date. Leave it blank to use the server's limit, which is also the most you can set.

## What notifications carry

The **Privacy** section has three switches for what leaves the app about this community:

| Switch | When it's off, or on for hiding |
|---|---|
| **Phone and desktop notifications** | Nothing about this community is sent to a phone or the desktop app. |
| **Email notifications** | Nothing about this community is sent to a mailbox. |
| **Hide notification details** | A notification that leaves the app says only what kind of thing happened. |

Whoever runs the server answers the same three questions for every community, and **the stricter answer applies**. A community can be quieter than its server, never louder. Where the server has already decided, the switch says so.

With details hidden, a mention reaches a phone or mailbox as *"You were mentioned or answered"* with *"Open Initiative to see where."* The bell inside the app shows everything either way.

Sign-in codes, address confirmations, password resets and notices about somebody's own account aren't notifications. They belong to the account, and they're sent whatever these switches say. Turning phone notifications off stops this community's sends but keeps each member's registered devices, because those belong to the account.

Members keep their own [notification settings](../guides/notifications.md). These switches can make a channel unavailable, and can never turn one on for somebody who turned it off.

## AI features

**AI features** decides whether members can use AI features in this community. Off, nothing in it is sent to an AI provider. The switch appears only while the server has AI features turned on. See [AI features](../account/ai-features.md).

## Ranking search by engagement

**Rank search by engagement** puts what more members have recently opened or worked on a little higher in search, the command palette and pickers. It reorders results and never adds one.

What's kept is a rough level for each item, worked out every hour from the last 7 days of opens and changes in this community. An item gets a level only once three different people have engaged with it. The level names nobody and holds no count, and it's read only beside items the reader can already open. See [What Initiative keeps about use](data-and-compliance.md#what-initiative-keeps-about-use).

Turn it off and the levels are deleted at the next hourly pass, and results are ordered by the match alone. Whoever runs the server can turn ranking off for every community with **Let communities rank results by engagement**, and then this switch says so. Each member can leave their own activity out with **Count my activity toward search ranking**, under **My Settings → Privacy**.

## Turning something off

Turning something off destroys nothing.

| If you | Then |
|---|---|
| **Disconnect** a provider | Its button comes off your sign-in page and nobody new arrives through it. Nobody is signed out, no account changes and no membership is removed. If a requirement names it, you're asked to lift that first. |
| Lift a requirement | Members stop being asked. |
| Turn somebody's **API access** back on | The keys they already had reach your community again. |
| Turn off **Sign in again every 12 hours** | Members stop being signed out for being idle the next time the app renews their session, and go back to the server's session length at their next sign-in. A session already held to 12 hours keeps that limit until it ends. |
| Turn **Phone and desktop notifications** back on | This community's notifications reach phones again, from the next one sent. |
| Turn off **Hide notification details** | The next notification to leave names what it's about. Ones already sent aren't changed. |
| Turn **Rank search by engagement** back on | Levels are worked out again at the next hourly pass, from the past 7 days. |

If whoever runs the server takes away **Its own sign-in** or **Its own security standard**, that half of the tab closes, and the settings it held stop applying. They stay saved, and apply again if the option comes back. A requirement to arrive through your providers is the exception: it stays in force when **Its own sign-in** is taken away, while its passkey part stops applying. Connections and group rules carry on as they were.

??? techspec "What each control is"

    **The two options** are community rules set by the deployment: `community_sign_in` (**Its own sign-in**) and `security_standards` (**Its own security standard**). Every community rule names the option it needs, and every point that enforces one asks whether the community holds it. Taking an option away leaves the rule's row in place.

    **Connections** are rows joining the community to a provider in the server's registry, narrowed by a claim and the values that count. Matching is case-insensitive and any-one-of, and a narrowing with no claim or no values admits nobody. The values a session asserted are recorded when it signs in, and which values count is read live, so editing a narrowing applies without anybody signing in again.

    **Group rules** map one group value, per provider, to a community role and optionally an initiative and a role in it. They reconcile in both directions at each sign-in through that provider, and on the background refresh for identities holding a refresh token: they grant what they match, and release only what that provider's earlier syncs granted.

    **Custom role rules** map one group value, per provider, to a custom role. They're stored in the community's own schema, beside the roles, and read in order: the first match wins. An assignment records the provider that gave it, so a later sync through that provider changes or releases only its own.

    **The sign-in requirement** is a rule per community for members (`auth_policy`) and one for guests (`guest_auth_policy`): open, or required, naming a provider and the methods a session must carry (`sso`, `totp`, `passkey`). `password` and `email_otp` are refused by a database constraint. It's enforced at the gate every community request passes, which answers with a step-up challenge, and again in the database's row-level security. The provider part applies whatever options the community holds, and the passkey part only while it holds `community_sign_in`.

    **The security standard's settings** are rules that need `security_standards`: `require_second_factor`, `enforce_compliance_session`, `allow_push_notifications`, `allow_email_notifications`, `redact_notification_content`, `allow_ai`, `allow_engagement_ranking`, `guest_max_days`, and `api_keys`, which is set per member.

    **Notification delivery** reads the community's three rules beside the server's own when a notification is sent, so tightening the server's answer covers every community at once. Redaction is applied to the message as it's built for the channel it leaves on. The stored notification the bell reads is unchanged.

    **Engagement ranking** is read with the server's own switch by the hourly pass. Each person counts once per item, at their weightiest engagement: an open counts 1, or half that when it came from search or the activity feed, and a change counts 2. Engagement halves in weight every two days over a seven-day window. An item needs three different people before it has a level, which is `floor(log2(1 + score))`, capped at 7. A search match's rank is multiplied by `1 + 0.1 × level`. Levels sit in each community's own schema and are read through the same per-item gate as the item. Plug-ins can't read them.

    **API access** is checked on every request made with a personal key, so a key is judged when it's used, not when it was created.

    **Session length** is twelve hours, `min()`-ed with the server's `session_max_hours`. Sessions come under it at their next sign-in, in a browser and in the apps alike. The idle limit is fifteen minutes, or the server's `session_idle_minutes` if shorter. It's carried by the session's own clocks rather than checked on each request: the refresh row expires that far out, each renewal reads the window again and re-stamps it from the person's last input (which the app reports as `idle_seconds`), and the access token never outlives the row it names. An idle session lapses on its own.

## Related

- [Working with communities](../guides/communities.md): the other settings tabs, and what the superadmin seat is for.
- [Single sign-on](../running-a-server/single-sign-on.md): for whoever runs the server and registers the providers.
- [API keys & integrations](../account/api-keys-and-integrations.md): what a personal key is, from a member's side.
- [Two-factor authentication](../account/two-factor-authentication.md) and [Passkeys](../account/passkeys.md): what you're asking members for.
