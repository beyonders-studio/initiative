---
icon: lucide/door-open
---

# Guests

The visiting choreographer who needs the rehearsal schedule for three weeks. The accountant who needs one spreadsheet, once, in April. The new treasurer's predecessor, who has agreed to "stay on for a bit to hand over", which everybody understands to mean a month and fears will mean a year.

None of them should be a member. Make them a **guest**: somebody in your community for a set number of days, who reaches only what you gave them, takes no seat, and leaves on their own when the time is up.

A guest has an ordinary account. They sign in, comment, get notified and edit what you let them edit, like anybody else. They just see a much smaller community than you do.

## Before you start

Guests are switched on per server, and start **off**. If your community settings have no **Guests** tab, either the server doesn't allow guests or your community isn't taking any. Ask whoever runs your server.

Running it yourself? Turn on **Allow guests** under **Settings → Platform → Community**.

## Inviting a guest

**Community settings → Guests → Invite a guest**. Admins only.

| Field | What it sets |
|---|---|
| **Days the guest stays** | How long they're in, counted from the moment they join — not from when you made the link. |
| **Max uses** / **Expires in (days)** | The link itself: how many people it lets in, and when it stops working. One use and seven days to start. |
| **Initiatives they join** | Whole initiatives, joined with the initiative's **Member** role. |
| **Items they get** | One project, file or other item at a time, as **Viewer** or **Editor**. |

Pick any mix of the last two. Then **Generate guest invite**, copy the link, and send it however you like. Whoever opens it signs in or makes an account, and is in.

Guest links are listed on the Guests tab, under the form, with what each one gives. Deleting one there stops it working.

## What a guest reaches

| Given | They get |
|---|---|
| An initiative | What its Member role allows there, as any member would. They show in its member list marked **Guest**. |
| An item | That item, at the level you picked. Its initiative shows up for them, but not who else is in it. |

Comments, reactions, bookmarks, mentions and notifications all work on those things. Anything a guest makes stays with the community after they've gone.

A guest in an initiative can [ask for access](sharing-projects-and-files.md#asking-for-access) to what's in it, as any member can. A guest given one item can only ask to edit that item: nothing else in its initiative turns up for them to ask about.

Everything else isn't there for them: other initiatives, the community's member list, its initiative directory, plug-ins and settings. Like anything else they can't reach, it comes back "not found". See [Sharing & access](index.md#why-a-missing-thing-says-not-found-rather-than-denied).

## Seats

A guest takes no seat, so they never count towards the community's member limit. Guests have a limit of their own, shown on the **Usage** tab as **Up to N at a time** (or **Unlimited**). A guest whose time has ended frees their place straight away.

On your own server, that limit is yours to set per community: **Operator dashboard → Communities → Manage → Guests**. Blank means no limit, and `0` means the community takes no new guests, while those already in stay until their time ends. On a hosted server it comes with the community's plan.

## When the time runs out

The minute it ends, the door shuts. Within a few minutes after that they're removed from the community and its initiatives, exactly as if an admin had done it. Their account is untouched, and so is everything they made.

Want them back? Send a new guest invite. A guest can also leave early from the community rail with **Leave community**, like anybody.

## Managing guests

The **Guests** list on the same tab shows everybody currently here and when their **Time ends**. Each row's menu has:

- **Extend** — sets a new end, that many days from today.
- **Make member** — they stay for good and take a seat, so the community needs one free.
- **Remove from community** — ends it now.

## How long is too long

Two limits cap every stay and every extension, and the lower one wins:

- **The server's**, under **Settings → Platform → Community → Longest a guest may stay (days)**. 90 days to start.
- **The community's**, under **Community settings → Security → Guest stays**, for a community that has a Security tab. Blank uses the server's. Changing it leaves guests already here with the end date they had.

Switching **Allow guests** off stops every guest on the server from getting in, without removing anybody. Switch it back on and they carry on until their time ends.

## Guests' sign-in

A community with its own [sign-in](../security/community-security.md) can ask something different of guests than of members — a passkey, or one of its providers. It's the **Guests' sign-in requirement** card on the Security tab, and you don't have to meet it yourself to set it.

??? techspec "For the technically minded — how a guest is held"
    A guest is a community membership with the `guest` role and an end time (`guest_until`). The database admits the membership only until then, so access ends on the first request after it rather than when the clean-up job runs; that job removes the membership every five minutes through the same path as an admin's removal. A guest's requests run as the community's guest database role, which holds nothing on the community's settings, plug-ins, AI, imports, exports or moderation tables, and row-level security keeps their reads to the initiatives they're in and the items shared with them. Member counts and the member list leave guest memberships out.

## Related

- [Sharing projects & files](sharing-projects-and-files.md) — the Viewer and Editor levels a guest gets.
- [Working with communities](../guides/communities.md#inviting-people-admins) — inviting members.
