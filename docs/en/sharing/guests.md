---
icon: lucide/door-open
---

# Guests

Some people need in for a little while: the visiting choreographer who needs the rehearsal schedule for three weeks, the accountant who needs one spreadsheet, once, in April, and the old treasurer who agreed to "stay on for a bit to hand over", which everybody understands to mean a month and fears will mean a year.

None of them should be members. Make them a **guest**: somebody in your community for a set number of days, who reaches only what you gave them and leaves on their own when their time is up. Guests don't count toward your community's member limit.

A guest has an ordinary account. They sign in, comment, get notifications and edit what you let them edit, like anybody else. They just see a much smaller community than you do.

## Who can invite guests

Community admins invite guests, from the **Guests** tab of Community settings. Guests are switched on server by server, and start off. If your Community settings have no **Guests** tab, either your server doesn't allow guests or your community isn't taking any, so ask whoever runs your server.

Running the server yourself? Turn on **Allow guests** under **Platform Settings**, **Community**.

## Invite a guest

1. Open **Community settings** and select **Guests**.
2. Under **Invite a guest**, set **Days the guest stays**. Their time counts from the moment they join, not from when you make the link.
3. Set **Max uses** and **Expires in (days)** for the link itself. A new link starts at one use and seven days.
4. In **Initiatives they join**, pick any whole initiatives they should be in.
5. Under **Items they get**, search for a project, file or other single thing and pick it.
6. Choose **Viewer** or **Editor** beside each thing you picked.
7. Select **Generate guest invite**.
8. Select **Copy invite link**, the copy button beside the new link.
9. Send the link however you like.

Mix initiatives and single things however you need. Whoever opens the link signs in or makes an account, and they're in. Your guest links are listed under the form, with how long each guest stays and what each link gives; select the trash can beside one to stop it working.

## What a guest can reach

| You gave them | They get |
|---|---|
| An initiative | What its **Member** role allows there, as any member would. They show in its member list marked **Guest**. |
| A single thing | That thing, at the level you picked. Its initiative shows up for them, but not who else is in it. |

Comments, reactions, bookmarks, mentions and notifications all work on what they can reach. Anything a guest makes stays with the community after they've gone.

A guest in an initiative can [ask for access](sharing-projects-and-files.md#asking-for-access) to other things in it, as any member can. A guest given a single thing can ask to edit that thing, and nothing else in its initiative turns up for them to ask about.

Everything else in the community isn't there for them: other initiatives, the member list, the initiative list on the front page, plug-ins and settings. Like anything else they can't reach, it comes back "not found". See [Sharing & access](index.md).

## Guests and seats

A **seat** is one of the places your community's member limit allows. Guests don't take one, so they never count toward that limit. Guests have a limit of their own, shown on the **Usage** tab as **Up to … at a time**, or **Unlimited**. A guest whose time has ended frees their place straight away.

Whoever runs your server sets that limit for each community: on the **Operator dashboard**, under **Communities**, **Manage**, then **Guests**. Blank means no limit, and `0` means the community takes no new guests, while the ones already in stay until their time ends.

## When a guest's time runs out

The moment their time ends, the door shuts. Within a few minutes they're also removed from the community and its initiatives, exactly as if an admin had removed them. Their account is untouched, and so is everything they made.

Want them back? Send a new guest invite, or [extend their time](#give-a-guest-more-time) before it ends. A guest can also leave early with **Leave community** on the rail, like anybody.

## Give a guest more time

Admins can change a guest's stay, and so can anyone whose [custom role](../guides/running-a-community.md#custom-roles) includes **Members**.

1. Open **Community settings** and select **Guests**.
2. Under **Guests**, open the guest's menu.
3. Select **Extend**.
4. Type the number of **Days from now**.
5. Select **Extend**.

Their new end date is counted from today, and shows under **Time ends**. It can't run past the longest stay your community or server allows.

## Make a guest a member

Admins can do this, and so can anyone whose custom role includes **Members**.

1. Open **Community settings** and select **Guests**.
2. Open the guest's menu.
3. Select **Make member**.

They stay for good, on the Member role, and take a seat, so the community needs one free. Any initiatives set to [add every new member automatically](../guides/initiatives.md#add-every-new-community-member-automatically) take them in too.

## Remove a guest early

Admins can do this, and so can anyone whose custom role includes **Members**.

1. Open **Community settings** and select **Guests**.
2. Open the guest's menu.
3. Select **Remove from community**.
4. Select **Remove from community** to confirm.

Their visit ends now, the same as when their time runs out.

## Set the longest a guest can stay

Two limits cap every guest's stay and every extension, and the lower one wins:

- **The server's**, set by whoever runs it under **Platform Settings**, **Community**, **Longest a guest may stay (days)**. It starts at 90 days.
- **The community's**, which superadmins set under **Longest guest stay** on the **Security** tab of Community settings, for communities that have one. Leave it blank to use the server's limit.

Changing either leaves the guests already here with the end date they had. Turning **Allow guests** off stops every guest on the server from getting in, without removing anybody; turn it back on and they carry on until their time ends.

## Ask guests to sign in a certain way

A community with its own [sign-in settings](../security/community-security.md) can ask something different of guests than of members, like a passkey, or signing in through one of its providers. Superadmins set it on the **Guests' sign-in** card of the **Security** tab, and you don't have to meet the requirement yourself to set it.

??? techspec "How a guest is held"
    A guest is a community membership with the `guest` role and an end time (`guest_until`). The database admits the membership only until then, so access ends on the first request after it, rather than when the clean-up job runs; that job removes ended memberships every five minutes, through the same path as an admin's removal. A guest's requests run as the community's guest database role, which holds nothing on the community's settings, plug-ins, AI, imports, exports or moderation tables, and row-level security keeps their reads to the initiatives they're in and the things shared with them. Member counts and the member list leave guests out.
