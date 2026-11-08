---
icon: lucide/share-2
---

# Sharing projects, files and more

Every project, file, calendar, counter group, dashboard, post, wiki and contact decides for itself who in the initiative can open it. That's **sharing**. Somebody's [initiative role](initiative-roles.md) says which tools they can use at all, and sharing says which particular things in those tools they can reach. Both have to agree before they get in.

It works the same way for every tool, so learn it once and you're done.

## The three access levels

An **access level** is how much one person can do with one thing:

| Level | Can |
|---|---|
| **Viewer** | Open it and read it. |
| **Editor** | Read it and change it. |
| **Owner** | Everything an editor can, plus delete it, export it, and decide who else gets in. |

The owner is whoever made the thing, and each thing has one. The initiative's Moderators and the community's admins count as owners of everything in the initiative. Ownership moves only when a community admin [hands it on](../guides/running-a-community.md#hand-someones-things-to-another-admin).

Give people the lowest level that lets them do their job. Most people only ever need **Viewer** or **Editor**, and moving somebody up later takes two clicks.

## Who can see something new

Anything new starts out shared with everyone in its initiative as viewers, so the whole team can read it. Many of the windows for making something have **Advanced options**, where you can change that before you make it, for instance to keep a file to yourself until it's ready.

## Who can change sharing

A thing's owner can change who has access, and so can the initiative's Moderators and the community's admins. Editors can see who has access on the **Access** tab, but can't change it. Viewers don't see the tab.

## Share something with one person

You can share with anybody in the thing's initiative. Somebody outside it has to [join the initiative](../guides/initiatives.md#add-someone-to-an-initiative) first, or come in as a [guest](guests.md).

1. Open the project, file or other thing.
2. Select **Settings** at the top right.
3. Select **Access**.
4. If it says **All initiative members**, select that and choose **Restricted**.
5. Under **People**, select **Add people**.
6. Pick the person.
7. Choose **Viewer** or **Editor** beside their name.

Changes save as you make them, and the person can open it straight away. Switching to **Restricted** takes it away from the rest of the initiative, apart from the people and roles you name. To change somebody's level, pick a new one beside their name. To take them off, select the **×** beside it.

!!! screenshot "The Access tab"
    A project's **Access** tab with **Restricted** chosen, two people under **People** (one **Viewer**, one **Editor**), the owner's row and one role under **Roles**. Save as `docs/en/images/sharing/access-settings.png`.

## Share something with everyone who holds a role

Sharing with a role reaches everyone on that [initiative role](initiative-roles.md) at once, including the people put on it next month. It's the tidy option when a whole group should get the same thing, instead of adding eleven people one by one and forgetting the twelfth.

1. Open the thing.
2. Select **Settings** at the top right.
3. Select **Access**.
4. If it says **All initiative members**, select that and choose **Restricted**.
5. Under **Roles**, select **Add roles**.
6. Pick the role.
7. Choose **Viewer** or **Editor** beside it.

The Moderator role always appears there as a locked **Editor** marked **Full access**, because Moderators can open everything in the initiative anyway.

## Share something with the whole initiative, or take it back

1. Open the thing.
2. Select **Settings** at the top right.
3. Select **Access**.
4. Select the box under **Share**.
5. Choose **All initiative members** to open it to everyone in the initiative, or **Restricted** to keep it to the people and roles you name.
6. With **All initiative members**, choose **Viewer** or **Editor** for everyone.

Choosing **All initiative members** replaces any people and roles you'd named, and starts everyone at **Viewer**. When in doubt, start restricted. Widening access takes two clicks; un-sharing something people have already read takes a conversation.

Every settings tab has its own web address, so you can send somebody a link straight to a thing's **Access** tab instead of describing which three things to click.

## Change access on several things at once

Handy when a new volunteer joins a batch of work, and handier when somebody leaves. This works in the lists of projects, files, counters, dashboards, wikis and contacts, for things whose sharing you can change.

1. In the tool's list, select **More actions**, the **…** button.
2. Select **Select items**.
3. Tick the things you want. Hold ++shift++ and select another to take everything in between too.
4. Select **Edit access**.
5. Choose **People**, **Roles** or **All members**.
6. In **Action**, choose **Grant access** or **Revoke access** (for **All members**: **Share with all members** or **Remove all-members access**).
7. Pick the people or roles.
8. When you're granting or sharing, choose the **Permission level**.
9. Select the button at the bottom, which says what it's about to do, like **Grant 2 people**.

Archived things keep their sharing as it is, so **Edit access** says so when one is in your selection. Sharing with all members replaces the people and role shares on each thing; removing all-members access keeps them.

## Ask for access to something you can't open { #asking-for-access }

Somebody sends you a link to "the budget". You open it, and it's in your initiative, but nobody shared it with you, so you're looking at **You need access**. Asking takes ten seconds.

1. In **Access**, choose **View** or **Edit**.
2. Add a **Note** if it helps, like "for Thursday's meeting".
3. Select **Request access**.

The thing's owner gets your request, or its initiative's managers if nobody owns it. You hear back in your notifications when they share it, and until then the page shows you've asked.

The same offer turns up wherever you meet something you can't open:

- **A link or an embed** in a page shows **You can't see this**, with a way to ask.
- **A collection or a wiki** says how many of its files you can't see, and lets you ask for all of them at once.
- **Something you can read but not change** has **Ask to edit** at the top right.

There's one request per thing at a time, so asking twice just shows you've already asked. Things in initiatives you're not in don't offer this at all: they come back "not found", since as far as your account is concerned there's nothing there (see [Sharing & access](index.md)).

## Answer a request for access

Anyone who can change a thing's sharing can answer requests for it, so a request isn't stuck waiting for one person's vacation to end.

1. Select the request's notification, or open the thing's **Access** tab, where waiting requests sit under **Requests**.
2. Read who's asking, what they asked for and their note. A guest's request says the day their visit ends.
3. In **Access**, choose **View** or **Edit**. It starts at what they asked for.
4. In **Share with**, choose **This person** or **Everyone in the initiative**.
5. Select **Share**.

They're told, with a link. To say no, select **Decline** instead, ticking **Tell them** first if you want them to know. Without the tick, a quiet no stays quiet, and they can ask again. When one person asked for several files at once, **Share all** and **Decline all** answer the lot.

## People who can open everything anyway

Two kinds of people reach things whatever their sharing says, on purpose:

- **Moderators** of an initiative open everything in it. Keep that in mind for genuinely private material (see [Initiative roles](initiative-roles.md#the-two-built-in-roles)).
- **Community admins** open everything in their community, because somebody has to be able to find the thing that's gone missing.

??? techspec "How sharing is stored and checked"
    Sharing is recorded as grants naming one thing, a person or a role (or everyone in the initiative), and a level: read, write or owner. On every request the database checks whether the reader holds a grant, directly or through a role, or reaches the thing as a Moderator or community admin, before any data comes back. Because that check lives in the database beside the community and initiative boundaries, a link to something never grants access to it. See [How your data is kept separate](../security/how-your-data-is-kept-separate.md).

    That a thing exists is told to members of its initiative through a database view that returns only its kind, its id and whether it's in the trash, for the initiatives the reader is in and no others. A request for access is recorded beside the grants, and answering one writes ordinary grants.
