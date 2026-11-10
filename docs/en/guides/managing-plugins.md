---
icon: lucide/blocks
---

# Managing plug-ins

Once a plug-in is in your community, somebody has to look after it: finish setting it up, decide what it can reach, keep an eye on updates, and take it out again if it stops earning its place. That's the community's [superadmin](running-a-community.md#why-superadmin-is-separate). If that's not you, the parts of a plug-in that are yours (connecting your own account, letting it act as you) are on [Plug-ins & the marketplace](plugins-and-marketplace.md#use-a-plug-in).

Adding one in the first place is under [Add a plug-in to your community](plugins-and-marketplace.md#adding-a-plug-in). Everything below can be changed again later, so none of it is a one-way door.

## Open a plug-in's settings

1. Open **Community Settings**.
2. Select **Integrations**.
3. Under **Plug-ins**, select the arrow (**Open settings**) at the end of the plug-in's row.

The gear beside a plug-in's name in the sidebar opens its credentials, settings, placement and members without leaving the page you're on. What it can reach, and its updates, are only in Integrations.

Each row says at a glance whether a plug-in needs anything:

| Label | What it means |
|---|---|
| **Needs setup** | It's waiting for a credential or a setting before it can do anything. |
| **Setup problem** | Something it was given doesn't work. Where it can, the label says what. |
| **Update waiting** | A new version wants more than you agreed to. See [updates](#keep-a-plug-in-up-to-date). |
| **Comes with Initiative** | Your server adds it to every community. See [below](#plug-ins-that-come-with-your-server). |
| **Not set up on this server** | It needs something whoever runs your server hasn't connected. It's hidden from the sidebar until they do. |
| **Turned off** | Somebody turned it off. |

## Finish setting up a plug-in

Some plug-ins need a credential (an API key, or a sign-in to another service) or a setting of their own before they work. There are two kinds of credential, and the difference matters:

- **Community credential**: set once, by you, and used for everyone. Good for a shared account the whole group works through.
- **Your account**: each member connects their own, used only for them. Nobody else sees it, admins included. See [Connect your own account](plugins-and-marketplace.md#connect-your-own-account-to-a-plug-in).

To set the community's:

1. Open the plug-in's settings.
2. Under **Community credential**, fill in what it asks for and select **Save**, or select **Connect** if it signs in at the other service.
3. Under **Settings**, fill in anything else it needs, such as the prefix a task's reference starts with.

Each credential shows which service it's for and what it may do there, so you can decide before handing anything over. **Clear** removes a community credential, and **Reconnect** replaces one that signs in.

## Change what a plug-in can reach

1. Open the plug-in's settings.
2. Under **What this plug-in can reach**, tick or untick **Read** and **Read and change** for each kind of thing.
3. Select **Save**.

A line marked **This server doesn't allow it** stays off whatever you tick. The two standing lines, **Act as a moderator in the initiatives it's placed in** and **Act as an admin across your whole community**, start unticked; see [what they mean](plugins-and-marketplace.md#letting-a-plug-in-act-as-a-moderator-or-an-admin).

## Change where a plug-in works

A plug-in reads and changes things only in the initiatives it works in.

1. Open the plug-in's settings.
2. Under **Where this plug-in works**, pick **Every current initiative** or **Only the initiatives I choose**.
3. If you're choosing, tick the initiatives.

Each change saves straight away. With no initiatives chosen, the plug-in reaches nothing inside initiatives at all.

Who uses it in each initiative is that initiative's call, the way its tools are: **Roles** beside an initiative opens its Roles screen, where its managers decide (see [Plug-ins on a role](../sharing/initiative-roles.md#plug-ins-on-a-role)). Its managers and community admins can always use it there. What a plug-in adds to Community settings follows the [custom roles](running-a-community.md#custom-roles) your admins hold.

## See who has connected, and stop them

For a plug-in members connect their own accounts to, the **Members** part of its settings shows how many have, and who.

- **Revoke** deletes one member's stored credential and tells the plug-in to stop using it. They can connect again.
- **Block** does the same and stops them connecting again until you select **Unblock**.
- **Revoke everyone** does it for every member at once, after you confirm. The plug-in stays installed with its settings, and members can connect again afterwards.

**Acting as members**, below that, lists who has let the plug-in act in their name. **Revoke** beside a member stops it acting as them, and **Stop it acting as anyone**, after you confirm, stops it for everybody at once. Members can allow it again themselves.

## Keep a plug-in up to date

Plug-ins update themselves. Most new versions arrive quietly and nobody notices, which is the idea.

A version that wants **more** than you agreed to (something new to reach, or a new page inside initiatives) waits for you. You get a notification under **Waiting on you**, and the row says **Update waiting**.

1. Open the plug-in's settings.
2. Read what the new version asks for, listed under a line like **Version 2.0.0 wants to:**.
3. Select **Accept and update**, or **Decline**.

Declining keeps the plug-in as it is, on the version it's running.

To read every update before it lands, turn off **Update automatically** in the plug-in's settings. Each new version then waits for you to select its button, like **Update to 2.1.0**. When there's nothing new, it says **Up to date**.

## Rename or turn off a plug-in

In **Community Settings → Integrations**, the plug-in's name at the start of its row is a box you can type in. Change it and click away, and the new name shows in the sidebar.

**Turn off** hides the plug-in from everyone and keeps its setup. **Turn on** brings it back exactly where it left off. A turned-off plug-in stays listed here so you can find the switch again.

## Remove a plug-in

1. In **Community Settings → Integrations**, select **Remove** on the plug-in's row.
2. To have the plug-in delete what it holds about your community too, tick **Also erase its data**.
3. Select **Remove** (or **Remove and erase**).

What happens next:

- Anything it set up when it was added moves to the community's **Trash**, where it can be restored until the trash empties.
- Anything it owned stays where it is, with no owner. An admin can pick it up with **Claim all** under **Unowned content**, in **Community Settings → Users**.
- Every value it kept on items goes with it.
- Every credential it held, the community's and each member's, is deleted, and the plug-in is told to stop using them.
- The plug-in is told it was removed. It never learns your members' names or accounts, only a name of its own for each of them, and those stay the same, so if you add it back later it recognizes your community and picks up where it left off.

**Also erase its data** asks the plug-in to delete everything it holds about your community. Once it has, its names for your community and its members are forgotten, and adding it back starts afresh. You can't add it back until it has answered. A plug-in that never answers is given about four days, and then its names are forgotten anyway.

A plug-in is also told when your community is put on hold, and pauses its own work until the community is back. If a community is deleted for good, every plug-in that knew it is asked to erase what it holds first.

## Let a plug-in own things

Content usually belongs to a person, but it can belong to a plug-in, so a project a plug-in looks after isn't orphaned when the person who set it up moves on.

1. Open **Community Settings → Users**.
2. Open the actions menu on the row of the person who owns it now.
3. Select **Transfer ownership**.
4. Under **New owner**, pick the plug-in. Plug-ins are marked **Plug-in**.
5. Select **Transfer**.

This moves everything that person owns in the community. To hand over what nobody owns any more, select **Claim all** under **Unowned content** on the same page instead, and pick the plug-in there.

A plug-in can be given something only while it's turned on, works in the initiative where the content lives, and is allowed to change that kind of thing. One that owns something can decide who else gets access to it, if it's allowed to change sharing.

## Plug-ins that come with your server

Some plug-ins are added to every community by whoever runs your server, and say **Comes with Initiative**. You can rename them, set them up and decide where they work like any other, but there's no **Turn off** or **Remove**, and they update without asking. Whether they exist at all is your server's call.

Whoever runs your server can also take over plug-ins for a community. Then Integrations says **Whoever runs this server manages plug-ins for this community.** The plug-ins keep running, members go on connecting their own accounts, and you can revoke and block, but nothing there adds, changes or removes one.
