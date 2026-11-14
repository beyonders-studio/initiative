---
icon: lucide/shield-half
---

# Platform roles

Initiative has two sets of roles, and they never mix.

- **Community roles** (superadmin, admin and member) govern one community. See [Working with communities](../guides/communities.md).
- **Platform roles** govern the whole server: every community and every account. That's this page.

A platform role says what somebody may do to the server. It grants nothing inside a community: an owner who isn't a member of the book club sees the book club's projects exactly as often as anybody else who isn't a member, which is never. Reaching inside takes a [time-bound grant](#cross-community-access-break-glass-and-time-bound-grants).

## The ladder

Five rungs, each holding what the rung below holds and more. Everybody starts as a member.

| Role | What it adds |
|---|---|
| **Member** | Nothing server-wide. Their own communities and nothing else. |
| **Moderator** | Moderation: finding accounts and communities, renaming an account, clearing its picture and profile, suspending it, and asking for a [Moderate grant](#what-a-grant-can-say) to read a community's held content and [suspend the community](#suspending-a-community-as-a-moderator). No other kind of grant. |
| **Support** | Account recovery (reactivating and restoring, signing out everywhere, password and two-factor resets, revoking API keys), letting somebody answer the age question again, and asking for any kind of grant. |
| **Operator** | Managing accounts, roles and communities, deleting accounts, approving grants, breaking glass, writing [announcements](announcements.md) and [sign-in placement rules](single-sign-on.md#rules-on-a-provider). |
| **Owner** | The server's configuration: sign-in, email, push, branding, storage, plug-ins and everything else under **Settings → Platform**. Owners approve grants and break glass, and don't ask for grants themselves. |

### Capabilities

Each rung is a set of capabilities, and every feature checks a capability rather than a role name. This is the full list.

| Capability | Moderator | Support | Operator | Owner | What it opens |
|---|---|---|---|---|---|
| `users.read` | Yes | Yes | Yes | Yes | **Operator dashboard → Users**, and exporting it as CSV |
| `communities.read` | Yes | Yes | Yes | Yes | **Operator dashboard → Communities** |
| `content.moderate` | Yes | Yes | Yes | Yes | Renaming an account, clearing its picture, names, status line and decorations, suspending it, and holding a Moderate grant |
| `communities.suspend` | Yes | Yes | Yes | Yes | Suspending a community and lifting it, under a live Moderate grant on that community |
| `access.request` | Yes | Yes | Yes | | Asking for a grant. Without `access.request_any`, only a Moderate one. |
| `users.age_unblock` | | Yes | Yes | Yes | **Reset age question** |
| `users.manage` | | Yes | Yes | Yes | Account recovery: reactivate, restore, sign out everywhere, reset password, resend verification, password sign-in lock, two-factor, API keys |
| `access.request_any` | | Yes | Yes | | Asking for any grant: read, read and write, settings |
| `communities.manage` | | | Yes | Yes | A community's **Manage** sheet and status, and **Sign-in placement** |
| `announcements.manage` | | | Yes | Yes | **Operator dashboard → Announcements** |
| `users.delete` | | | Yes | Yes | **Delete user** |
| `roles.assign` | | | Yes | Yes | Changing somebody's **Platform role** |
| `data.bypass` | | | Yes | Yes | Breaking glass |
| `access.approve` | | | Yes | Yes | Approving, denying and revoking grants |
| `config.manage` | | | | Yes | Every **Settings → Platform** tab |
| `plugins.manage` | | | | Yes | **Plug-in services**, under **Settings → Platform → Integrations** |

A suspended account holds no capabilities at all, whatever its rung, and gets them all back when the suspension lifts.

A grant also counts only while its holder's rung may hold it. Demote somebody and any grant their new rung couldn't ask for stops working at their next request.

## The owner

The first account registered on a new server becomes its owner. Owners are the only ones who can change the server's configuration, so Initiative refuses to demote, delete or deactivate the last account that holds `config.manage`.

!!! warning "Keep more than one owner"
    Initiative won't let you remove the last owner, but an owner who has lost their phone, their password and their recovery codes is still an owner nobody can reach. Make sure a second person can change settings.

## Where staff work

Platform staff have two areas, and each shows only the tabs its reader may use.

| Area | Tab | Who sees it |
|---|---|---|
| **Operator dashboard** | **Users** | Moderators and above |
| | **Communities** | Moderators and above |
| | **Sign-in placement** | Operators and owners |
| | **Announcements** | Operators and owners |
| | **Access** | Moderators, support and operators to ask; operators and owners to approve and break glass |
| **Settings → Platform** | **Authentication**, **Security**, **Branding**, **Email**, **Push notifications**, **Community**, **Storage**, **Intake** | Owners |
| | **Integrations** | Owners |

## Managing platform users

**Operator dashboard → Users** lists every account by **User ID**, **Handle** and **Status**, with **Filter by handle…** above it. IDs count up as accounts are made, so sorting by ID sorts by when people joined. **Export all as CSV** takes the whole list, and **Export** in a row's actions menu takes one account.

![Operator dashboard › Users](../images/running-a-server/operator-users.png)

**Manage** opens everything you may do to one account. The server works out what's offered for each account and each viewer, so a control you'd be refused never appears. Nothing is offered on an account above your own rung, and nothing on your own account, which you change from your own settings.

| Control | What it does | Shown | Needs |
|---|---|---|---|
| **For case** | Notes each act you take in the panel on the case you choose, by handle and the name of the act. Optional. | Where your [operations community](operations-community.md) takes cases you can read | |
| **Username** | Changes the handle they're addressed by. The number after it stays. | Always, unless anonymized | Moderator |
| **Profile picture** | Takes the picture down. They're told, and can upload another. | When they have one | Moderator |
| **Names in communities**, **Status line**, **Decorations** | Clears them, for something that breaks your terms. Names clear in every community they're in. They're told what was cleared, never by whom, and can set each again. | When they have one | Moderator |
| **Suspended** | Puts the account in time out, with a reason you write for them. They can sign in and see one screen: that they're suspended, your reason, and [who to contact](operations-community.md#who-to-contact). Everything else, their platform role included, is out of reach until you lift it. Nothing is deleted. | Active or suspended accounts | Moderator |
| **Platform role** | Moves them up or down the ladder. You can't grant a rung above your own, or change somebody already above you. | Active accounts | Operator |
| **API keys** | **Revoke** switches off every key the account holds at once. The keys stay on their list marked disabled, and they can make new ones. | When a key still works | Support |
| **Two-factor authentication** | **Clear** takes off an authenticator they've lost along with their recovery codes. They're signed out everywhere and emailed, then sign in the usual way and set it up again. | When they have one | Support |
| **Sessions** | **Sign out everywhere** ends every session on every device and closes its open connections. They sign in again, and anybody else who had the account doesn't. | Active or suspended accounts | Support |
| **Password** | Emails them a link to choose a new one. | Active accounts, while password sign-in is on | Support |
| **Email address** | **Resend** sends the confirmation letter again. | Active accounts not yet confirmed | Support |
| **Password sign-in** | **Turn back on** lifts the lock that too many wrong answers set. | While locked | Support |
| **Age question** | Lets them answer again, for a mistyped year. Nothing else changes, and no birthday is recorded either way. See [Asking members their age](configuration.md#asking-members-their-age). | After an under-age answer | Support |
| **Deactivated** | Brings the account back. It returns with no communities, and they rejoin the ones they want. | Deactivated accounts | Support |
| **Deletion pending** | Calls off a deletion. Everything is where it was, communities included. Signing in during the window does the same. See [How long deleted things are kept](configuration.md#how-long-deleted-things-are-kept). | Deleted accounts not yet erased | Support |
| **Cases** | How many open cases the account filed or is the subject of, with a link to each. A link opens only for somebody who can read the project the case is kept in. | Where the operations community takes cases | |
| **Delete…** | See below. | Unless anonymized | Operator |

The password lock works like this: five wrong passwords or codes within 15 minutes switch password and code sign-in off for 15 minutes. The second lock within 24 hours lasts an hour, and the third and every one after it four hours. It ends on its own, or when they reset their password from the emailed link. Passkeys and sessions already open keep working throughout.

### Delete an account

**Delete…** asks how thorough to be.

| Choice | What happens | Undo |
|---|---|---|
| **Deactivate** | They can't sign in, and their memberships are dropped. Their details and content stay. | **Reactivate** |
| **Anonymize (soft delete)** | The account disappears for everybody else and keeps everything it holds. It's erased when the server's window ends (30 days unless [changed](configuration.md#how-long-deleted-things-are-kept)), unless they sign back in or you restore it. | Until the window ends |
| **Hard delete (purge)** | Everything is removed, including tasks, comments and anything else they wrote. The confirm step offers **Delete with the recovery window instead**, one tick away. | Never |

A deactivated account can be anonymized or purged, and an anonymized one only purged.

One thing blocks deleting an account: holding a community's only superadmin seat. Either the account holder makes another member superadmin first, or you [break glass](#break-glass) into the community and, from its **Settings → Users**, appoint somebody. Where nobody is left to hand it to, delete the community from its **Settings → Danger zone**, under the same grant. Content they owned is released on the way out for the community's admins to claim.

## What you decide per community

**Operator dashboard → Communities** lists every community on the server, deleted and suspended ones included, with its **ID**, **Users**, **Storage limit** and **Status**. Each row offers what your role allows:

| Control | Who |
|---|---|
| **Request access** | Moderators (a Moderate grant only), support and operators |
| **Suspend** or **Lift suspension** | Anybody holding a live Moderate grant on that community |
| The status menu | Operators and owners |
| **Break glass** | Operators and owners |
| **Manage** | Operators and owners |

**Manage** opens the settings only you can change for one community. Its own admins see them and can't edit them.

| Setting | What it does | Default |
|---|---|---|
| **Members** | How many people may belong. Guests take no seat. | No limit |
| **Guests** | How many [guests](../sharing/guests.md) it may have at once. `0` takes no new guests, and those already in stay until their time ends. | No limit |
| **Storage limit** | How much it may store, in gigabytes. See [per-community storage limits](object-storage.md#per-community-storage-limits). | No limit |
| **Its own sign-in** | See [Letting a community use a provider](single-sign-on.md#letting-a-community-use-a-provider). | Off |
| **Its own security standard** | Lets its admins refuse personal API keys and make members sign in again every 12 hours. | Off |
| **Banner artwork** | Lets it upload a banner image. Off, it picks a color, and a banner already uploaded keeps showing. | On |
| **Help requests** | Lets its members send a help request to your support project. Off, **Ask for help** opens the FAQ instead. It can only be switched on once a support project is set up (see [The operations community](operations-community.md)). | Off |
| **Its own AI connections** | Lets it set up AI providers of its own. Off, the ones it has are kept and not used. | On |
| **Its own plug-ins** | Lets it install and configure plug-ins. Off, the ones it has keep running as they are. | On |
| **Custom roles** | Lets its admins define roles that give people part of running the community. Off, the roles it has keep applying. | On |

Lowering a limit below what a community already uses blocks new uploads or members. It never removes a file or a member.

The sheet also lists **Who it counts as its own** for a community running its own sign-in, which is where you [agree its claim](single-sign-on.md#agreeing-a-communitys-claim).

### A community's status

Operators and owners set a community's status from its row.

| Status | Its members | Its admins | In community lists |
|---|---|---|---|
| **Active** | Everything, as normal | Everything, as normal | Listed |
| **Read-only** | Read, and change nothing | Read its content and keep running its settings, invites and roster | Listed |
| **On hold** | Nothing | Nothing | Gone for everybody |
| **Suspended** | Nothing | Nothing, settings included | Gone for members. Admins see it with a lock. |

**On hold** and **Suspended** each ask you to confirm first, because each takes everybody out in one click. Neither changes anything inside, and setting a community back to **Active** puts it all back.

- **On hold** tells the community's superadmins once, by email and in the app, that it's on hold and [who to contact](operations-community.md#who-to-contact). The email gives the date it's deleted if the hold is never lifted: 30 days on, unless you [changed the window](configuration.md#how-long-deleted-things-are-kept).
- **Suspended** tells nobody directly. Its admins find the lock on their sidebar, and opening it says the community is suspended and gives them the address.

Neither status keeps you out. A [grant or break-glass](#cross-community-access-break-glass-and-time-bound-grants) reaches a community whatever its status, which is how you look inside before deciding what happens to it.

### Suspending a community as a moderator

Any rung with `communities.suspend` suspends a community, and lifts its suspension, from its row, but only while holding a live [Moderate grant](#what-a-grant-can-say) on it. That way they're acting on a community they're looking at. Ask for the grant first, and an operator approves it.

A suspension starts from active, read-only, on hold or **deleted**. Suspending a deleted community stops its deletion countdown and keeps everything in it. Lifting a suspension puts the community back where it was. One suspended out of deletion goes back to being deleted, with its countdown started again from the beginning, so its owners get the whole window to notice.

### Deleted communities

Deleted communities stay in the list, marked with the date everything in them is destroyed: 90 days after deletion, unless you [changed the window](configuration.md#how-long-deleted-things-are-kept). Until then nothing has been removed.

1. Select **Manage** on the community's row.
2. Select **Restore community**.
3. Under **Comes back as**, choose its status.
4. If nobody is left who can run it, choose an account under **Who runs it**. They become its superadmin.
5. Select **Restore**.

It comes back exactly as it was, apart from its plug-in connections, which ended when it was deleted. Its admins can reconnect them.

## Cross-community access: break-glass and time-bound grants

Nobody holds a standing way into communities they don't belong to, platform staff included. When staff need to reach a community, they take explicit, time-bound, recorded access instead, from **Operator dashboard → Access**. Each grant reaches one community, ends on its own, and leaves a record naming who took it and why. [How your data is kept separate](../security/how-your-data-is-kept-separate.md) explains how the database enforces it.

### What a grant can say

A grant names what it reaches, in two halves asked for separately.

| Half | Level | What it reaches |
|---|---|---|
| **Content access** | **Read-only** | Everything the community holds, to read |
| | **Read & write** | The same, and editing what's already there. It doesn't create new content or manage members and permissions. |
| | **Moderate** | Everything, including [held](operations-community.md#held-content) content, to read. It changes nothing. Only rungs with `content.moderate` may hold one, and it's never self-issued. |
| **Settings access** | **Admin** | The community's configuration that its admins run, and nothing inside it |
| | **Superadmin** | The configuration its superadmin seat holds as well, sign-in included |

A settings grant on its own shows the configuration. Changing it also takes a live **Read & write** content grant on the same community. Somebody helping with a moderation setting has no business in anybody's files, and this is how they don't end up there.

Ask for one half, the other or both. Each is approved and recorded on its own. You can hold one pending or live grant per half per community at a time.

| Longest grant | Moderator | Support | Operator | Owner |
|---|---|---|---|---|
| By request | 4 hours | 8 hours | 24 hours | |
| By breaking glass | | | 4 hours | 4 hours |

The clock starts when the grant is approved, not when it's asked for.

### Request access

Moderators, support and operators ask; somebody else approves.

1. Open **Operator dashboard → Access**, or select **Request access** on the community's row under **Communities**, or in a case's **Access** section.
2. Under **Request access**, choose the **Community**.
3. Choose the **Case** it's for, if asked (see [Grants and their cases](#grants-and-their-cases)).
4. Choose **Tell the community**, if offered.
5. Choose a level under **Content access**, **Settings access** or both. A moderator is offered **Moderate** alone.
6. Choose a **Duration**: 1, 4, 8 or 24 hours, up to your rung's longest.
7. Write the **Reason**. Only approvers read it.
8. Select **Request access**.

Every operator and owner is notified. The request shows under **My requests**, where you can cancel it while it waits, and you're notified when it's decided.

### Approve or deny a request

Operators and owners do this. Nobody can approve their own request.

1. Open **Operator dashboard → Access**.
2. Under **Approvals → Pending requests**, read who's asking, for which community, at what level and for how long, and why.
3. Select **Approve** or **Deny**.

To end a grant early, select **Revoke** beside it under **Active grants**. The holder is notified either way.

### Break glass

For an emergency, an operator or owner issues themselves a grant that's approved the moment it's made. Breaking glass gives both halves at once, **Read & write** content and **Superadmin** settings, because an emergency is no time to discover you asked for the wrong shape. Each half is recorded separately, so the log says exactly how far it went.

1. Open **Operator dashboard → Access**, or select **Break glass** on the community's row.
2. Under **Break glass**, choose the **Community**.
3. Choose a **Duration**: 1, 2 or 4 hours.
4. Write the **Reason**.
5. Choose a **Case** and **Tell the community**, if offered. Breaking glass doesn't require a case.
6. If asked, enter **Your authenticator code** (a recovery code works too), or select **Break glass with a passkey**.
7. Select **Break glass**.

You can't break glass into a community you're a member of, since you already have your way in, or while you hold a live grant to it. Where the operations community takes security cases, every break-glass opens one for review.

!!! info "When breaking glass asks for your second factor"
    Breaking glass asks for your own authenticator code or passkey, at that moment, if you have one set up that the server still offers. It also asks everybody who can break glass if you've [required two-factor authentication for platform roles](configuration.md#requiring-two-factor-authentication). Somebody whose identity provider ran a second factor on the way in is covered by that sign-in. Anybody else without one is sent to **Security** in their own settings first, which takes about a minute.

    A recovery code answers too, which matters, because the phone is the thing most likely to be missing in the hour you need this.

!!! info "A grant is never a membership"
    Whatever it reaches and whoever holds it, a grant runs out, so anything that would outlive it stays out of reach. A grantee can't answer a request to join an initiative, for instance, because the membership on the other side of that answer has no end date.

### Grants and their cases

Where your [operations community](operations-community.md) takes security, moderation or support cases, a request has to name the case it's for. The picker offers up to 50 open cases you can read, and the case must be about the community you're asking for, or about no community yet, in which case the request settles it.

The case hears what becomes of the grant:

- that it was asked for, and how it was decided. Approval moves a case still waiting to be picked up into progress.
- each moderation act or suspension taken under it.
- what it did, once an hour while it's live, and in full when it ends: what was read, counted by kind, and up to 20 changes listed by name, with who revoked it if somebody did.

The case is only ever told ids, counts and the names of routes and acts, never what the community holds. A case lists its grants in its **Access** section, with **Request access** to ask for another. A request started from a community's row by a moderator, or from a case's **Holds**, starts on **Moderate**.

#### Telling the community

The case also decides whether the community hears about it. Its superadmins get an email naming the level, the kind of case, when, and your support contact. The email never includes the reason, which is for whoever approves it.

| Case | The community is told |
|---|---|
| Support | Always, when the access starts. You're working on their behalf, so they hear about it. |
| Security or moderation | Your choice on the form: **Don't tell it**, **When access starts** or **Once access has ended**. The last one is for an investigation the community shouldn't hear about until it's done. |
| No case | Not at all |

"When access starts" means on approval, or the moment glass is broken. A denied request touched nothing, so nobody is told about it. Approvers see the choice beside the case number.

## Where operations work lands

Security notes, moderation reports and support requests each open a case in one community of your choosing, the operations community. Setting it up, the kinds of case, held content and the contact addresses notices give all have their own page: [The operations community](operations-community.md).

## Announcements

Operators and owners write announcements: notices shown in a dialog to the people using the server, for a change somebody has to act on or would otherwise be confused by. See [Announcements](announcements.md).

## Related

- [The operations community](operations-community.md), where cases, holds and contact addresses live.
- [Announcements](announcements.md), for telling everybody something.
- [Configuration](configuration.md), for the server's own settings.
- [Working with communities](../guides/communities.md), for community roles and the superadmin seat.
- [How your data is kept separate](../security/how-your-data-is-kept-separate.md), for the access model behind all of this.
