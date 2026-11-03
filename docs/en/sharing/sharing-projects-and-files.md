---
icon: lucide/share-2
---

# Sharing projects & files

The last and most precise layer: who can reach one **specific** project or file.

It works identically for both, so learn it once and you're done.

## The three levels

| Level | Can do |
|---|---|
| **Viewer** | Open it and read it. |
| **Editor** | Read it **and** change it. |
| **Owner** | Everything an editor can, **plus** decide who else gets access. |

Pick the lowest level that lets somebody do their job. Most people only ever need Viewer or Editor, and you can always move them up later.

## Who you can share with

- **A person** — one specific member of the initiative.
- **A role** — *everyone* holding that [initiative role](initiative-roles.md), in one go. Share with "Cast" and every cast member gets it, including the people you add to that role next month.

Sharing with a **role** is the tidy option when a whole group should have the same access. Set it once instead of adding eleven people individually and forgetting the twelfth.

![Choosing who can access a project](../images/sharing/access-settings.png)

## Open, or restricted

- **All initiative members** — everyone in the initiative can reach it. Good for things the whole team should see.
- **Restricted** — only the people and roles you name. Good for anything you'd rather not explain later.

When in doubt, start restricted. Widening access takes two clicks; un-sharing something people have already read takes a conversation.

## Changing access later

Open the **Access** tab in a project's or file's settings whenever you like — add people, change a level, remove somebody. Changes apply immediately.

Every settings tab has its own web address too, so you can send somebody a link straight to a tool's sharing options instead of describing which three things to click.

You can also **change access on several things at once**. In a list of files, projects, queues, counters, dashboards or wikis, open **More actions**, choose **Select items**, pick what you want, then **Edit access**. Handy when a new teammate joins a batch of work, and handier when somebody leaves. Archived things keep their sharing as it is, so a selection with one in it says so.

You don't have to click each card individually, either. Click the first, hold ++shift++, click the last, and everything between comes with it. Shift-clicking away from a card you just unticked clears that run the same way. (++shift+enter++ or ++shift+space++ does it from the keyboard.)

## Asking for access

Somebody sends you a link to "the budget". You click it. It's in your initiative, but nobody shared it with you, and now you're looking at a page that says **You need access**.

Pick **View** or **Edit**, add a note if it helps ("for Thursday's meeting"), and press **Request access**. The owner hears about it. If nobody owns it any more, the initiative's managers do.

The same offer turns up wherever you meet something you can't open:

- **A link or an embed** in a page shows "You can't see this", with the same button.
- **A collection or a wiki** says how many of its files you can't open, and asks for all of them at once.
- **Something you can read but not change** has **Ask to edit**.

Ask as often as you like. There's one request per thing at a time, so pressing the button twice just tells you you've already asked.

## Answering a request

The notice opens the request. So does the **Access** tab, which lists anything waiting above the people who already have access. You see who's asking, what they asked for and their note, and a guest is marked with the day their access ends.

- **Share** gives them what they asked for. Change **View** to **Edit** or back before you press it, or choose **Everyone in the initiative** to open it to the whole team while you're at it. They're told, with a link.
- **Decline** says no. They're only told if you tick **Tell them**, so a quiet no stays quiet. They can ask again.

Anyone who can change who has access can answer, so a request isn't stuck waiting for one person's holiday to end.

## Three things worth remembering

- **Initiative membership comes first.** You can only share with somebody already in the initiative. If they're not, [add them there](../guides/initiatives.md#adding-members) first — the box won't offer them otherwise.
- **Moderators see everything.** A member with the [Moderator role](initiative-roles.md#the-two-built-in-roles) opens the item regardless of anything on this page. That's intended, and worth remembering for genuinely private material.
- **Community admins see everything in their community.** Also by design. Somebody has to be able to administer the place.

??? techspec "For the technically minded — how item sharing is stored and checked"
    Per-item sharing is recorded as grants naming a project or file, a person *or* a role, and a level (view / edit / own). On every request the database evaluates whether the current user satisfies the grant — directly, through a role they hold, through the initiative's Moderator role, or as a community admin — before any data comes back. Because that check lives in the database alongside the community and initiative boundaries, the link to a project is never the thing that grants access to it. See [How your data is kept separate](../security/how-your-data-is-kept-separate.md).

    That something exists is told to a member of its initiative through a database view that returns its kind, its id and whether it's in the trash, for the initiatives the reader is a member of and no others. A request is recorded beside the grants, and answering one writes ordinary grants.

## Related

- [Initiative roles](initiative-roles.md) — sharing with whole roles at once.
- [Sharing & access overview](index.md) — how this fits with the other layers.
