---
icon: lucide/users
---

# Your first community

A community is one group's space: the people, and everything they're working on. Your book club is one community and your day job is another, and nothing crosses between them. You need to be in one before you can do much.

There are three ways in. Somebody invites you, you find one that's listed publicly, or you start your own.

## Join a community from an invite link

This is how most people arrive.

1. Open the invite link.
2. Sign in, or [create your account](create-account.md#sign-up-from-an-invite-link) if you don't have one.
3. Select **Accept invite**.
4. Select **Continue to Initiative**.

The community's icon appears in the strip down the left, and you can see the initiatives you've been added to.

!!! note "If the invite won't work"
    Invite links can run out after a date or a number of uses. That's the link's fault, and definitely not a comment on you as a person. Ask whoever sent it for a new one.

## Find a community to join

Some communities list themselves so anyone on the server can find and join them, with no invite and no waiting for approval.

1. Select **Join a community** in the strip down the left.
2. Browse by category, or type into **Search communities**.
3. Select **Join** on the community you want.

The first time, Initiative asks your date of birth once, because listed communities are for people 16 and older. No **Join a community** button? Your server doesn't run a directory, and everything there works by invitation. More in [Find a community to join](../guides/communities.md#finding-a-community-to-join).

## Start your own community

You can make a community whenever your server allows it. If there's no **+** in the strip, it doesn't; ask a community admin to invite you, or whoever runs the server to make one for you.

1. Select **Create Community** (the **+**) in the strip down the left.
2. Type a **Community name**, usually whatever your group is called: "Fairview Bakery", "PTA Committee", "The Nguyens".
3. Add a **Description** if you like.
4. Select **Create community**.

You're its superadmin, the top seat, and Initiative takes you straight to setting up the first initiative.

![The Create a new community dialog, with Community name and Description](../images/getting-started/create-community.png)

## Set up your first initiative

A brand-new community is empty on purpose. An initiative is a body of work, like "Spring Play", "Engineering" or "Tuesday Night D&D", and only you know what yours is called. It holds that work's projects, files and other tools.

The **New initiative** box opens by itself after you create a community. Otherwise, select **Create initiative** on the community's home page.

1. Under **What is it called?**, type a **Name**, add a **Description** and pick a **Color** if you like, then select **Next: Tools**.
2. Under **What is it made of?**, keep the tools it needs and turn off the rest, then select **Next: Membership**.
3. Under **Who can get in?**, choose **Invite only**, **By request** or **Anyone can join**, then select **Next: Permissions**.
4. Under **What can they do?**, choose **Make things**, **See things** or **Managers only**.
5. Select **Create initiative**.

You can change all of it later, and turning a tool off never deletes what's in it. [Initiatives](../guides/initiatives.md) explains each choice.

## Add your first project

1. Open your initiative from the sidebar.
2. Select its **Projects** tab.
3. Select **Add Project**.
4. Type a name, then select **Create project**.

There's your first board. Put some tasks on it and you have a working setup; everything else in this guide is optional. Every other tool's tab has a button like this one.

## Invite people to your community

1. Right-click your community's icon in the strip down the left, or press and hold it on a touch screen.
2. Select **Invite members**.

An invite link is copied, ready to paste into the group chat. To set how long it lasts or how many people can use it, see [Running a community](../guides/running-a-community.md).

## Give your community an icon

Once you're in three communities, that row of tiny pictures is the only thing standing between you and posting the surprise party plans in the work one.

1. Select the gear beside your community's name at the top of the sidebar.
2. On the **Community** tab, under **Pictures**, choose an image for the **Icon**.

Any image works; Initiative crops it square for you.

??? techspec "A community is a hard boundary"
    Each community's content lives in its own database schema, created with the community, and every request is routed into exactly one of them. Reads and writes reach only the communities you belong to, enforced in the database rather than in the interface. Two browser tabs can sit in two different communities at once with no crossover. See [How your data is kept separate](../security/how-your-data-is-kept-separate.md).

Next, select the Initiative logo above your community icons. That's [your space](../guides/your-space.md): everything assigned to you from every community, on one page. After that, read [how Initiative is organized](../concepts/index.md), or skip straight to the [how-to guides](../guides/index.md). We won't ask which you picked.
