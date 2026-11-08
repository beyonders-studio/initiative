---
icon: lucide/at-sign
---

# Mentions & links

Work refers to other work. A write-up explains a project, a comment asks about a task, and the plan for the spring fundraiser points at the volunteer schedule that feeds it. Three characters handle all of that while you type:

| Type | To |
|---|---|
| `@` | Mention a person, who gets told |
| `#` | Link to anything that already exists in the initiative |
| `[[` | Link to a tool, or make one that doesn't exist yet |

They work in comments, in task and event descriptions, and in text documents, wiki pages and posts. And every link anybody writes shows up on the other end, under [Connections](#connections), so you can see what refers to a thing without keeping a list yourself.

## Mention someone with @

1. Type `@` and the first few letters of their name.
2. Pick them from the list.

Their name drops into your text. The list offers people in the initiative, and names match loosely, so a spelling you're not sure of still finds the right person.

Who hears about it depends on where you wrote it:

- **A comment** tells them as soon as you post it.
- **A task's description** tells them once, when their name first goes in. Rewording the sentence around them later doesn't ping them again, which they'll appreciate more than they'll ever say.
- **A text document** tells the people newly mentioned each time it saves.
- **A post or a wiki page** shows their name without a notification. A post tells its readers when it goes up anyway (see [Posts](posts.md)).

Somebody hears about a mention only if they can open the thing it's in. A mention that summons somebody to a page they can't see helps nobody, so [share it](../sharing/sharing-projects-and-files.md) with them first.

A mention always shows the name the person goes by today, their display name in this community or their handle, so it keeps up when they change it. Somebody who has left the community, or whose account was erased, reads as **Former member**. Searching for a person's name or handle finds what mentions them, even mentions written before they changed it.

## Link to something with #

1. Type `#` and a few letters of its name.
2. Pick it from the list.

Its name drops into your text as a link. The list covers everything in the initiative: every [tool](tools.md), and what's inside them, like tasks, events, counters, wiki pages and pictures. In a comment, linking a task also tells whoever it's assigned to.

Half the initiative named something "Planning"? Say what kind of thing you mean and the list narrows:

`#task:` `#project:` `#file:` `#collection:` `#calendar:` `#calendar-event:` `#counter-group:` `#counter:` `#dashboard:` `#post:` `#wiki:` `#wiki-page:` `#contact:` `#tag:`

You never have to use those. `#` on its own searches the lot.

The list reaches only this initiative (the document's own, when you're writing in one), so a community stuffed with matching tasks can still come back empty. When it does, the picker says the initiative is the limit, so you aren't left retyping the same word at an empty box.

## Link to a tool, or make one, with [[

`[[` offers the [tools](tools.md) in this initiative: projects, files, calendars, counters, dashboards, posts, wikis and contacts, whichever the initiative has switched on.

1. Type `[[` and a few letters of the name.
2. Pick it from the list.

The difference from `#` is what happens when nothing matches. In a comment, a description, a text document, a wiki page or a post, `[[` offers to make it on the spot, so you don't abandon the sentence you were halfway through:

1. Type `[[` and the new name.
2. Select **Create "…"** at the end of the list.
3. Under **What kind of thing is it?**, pick a tool.
4. Select **Create**.

The new thing lands in this initiative, and the link drops into your sentence. That's why `[[` reaches tools and `#` reaches everything: a tool needs only a name and an initiative, while a task needs a project and an event needs a calendar and a time, which nobody can conjure from half a sentence. Only tools this initiative has switched on, and that your role can make, are offered.

In a text document, wiki page or post, `![[` shows the thing in full rather than linking to it. See [Embeds](editor.md#embeds).

!!! note "`#` and `@` can't go in names"
    Both already mean something while you're writing, so a name or title can't contain either. Initiative tells you when you try, instead of quietly making a reference nobody can follow.

## What a link does when things change

A link points at the thing, not its name. Rename a task and every sentence linking it says the new name, in every document and every comment, without anybody editing anything.

If what you linked gets deleted, or was never shared with you, the link keeps the words it was written with, grayed out and not clickable. It never claims that something you can't see doesn't exist, and it never leaves a hole in the middle of a sentence.

An exported PDF or Word file shows the name the thing had when the link was written, since paper can't keep itself up to date.

Want a link that shows a task's status or an event's date as well as its name? That's a [smart chip](editor.md#smart-chips).

## See what something is connected to { #connections }

Every tool has a **Connections** section, and so do the things inside one: a task, an event, a wiki page, a contact. It lists what this links to and what links to it, grouped by how they relate:

| Heading | Means |
|---|---|
| **Attached** | The files this runs on |
| **Blocked by** | What has to happen first |
| **Blocking** | What's waiting on this |
| **Part of** | The bigger thing this belongs to |
| **Made up of** | The pieces it's built from |
| **See also** | Related, with no stronger claim than that |
| **Links to** | Everything this mentions with `#` or `[[`, or shows in a chip or an embed |
| **Mentioned in** | Everything that mentions this |

**Links to** and **Mentioned in** write themselves from what people type. Edit the words and they follow. A page pointing at itself doesn't count.

Each card shows the thing's current state where it has one (a task's column, an event's date), so a connection is never just a name.

## Link two things and say how they relate { #relations }

A link records how two things relate: what a task is waiting on, which file explains a project. You need to be able to edit the thing you're linking from. Links stay inside one initiative, apart from the community's own contacts, which any initiative's work can link to.

1. Open the thing and find its **Connections**.
2. Select **Add link**.
3. Search for the other thing under **Tools**, or for a person under **Members**.
4. Pick it.
5. Under **How the two relate**, pick the wording: **is attached to**, **is blocked by**, **is blocking**, **is part of**, **is made up of** or **is related to**.
6. Select **Add link**.

You get a sentence with both names in it, like **This task** *is blocked by* **Order the bounce house**, and both things list it under **Connections**. You find the thing first and pick the wording second, so nobody has to learn the vocabulary before they start typing.

Some wordings change the other thing too, so they need edit access on both ends. When you can only read the other thing, the dialog says "Some links can only be made from something you can change, and you can only read that." and offers the wordings you can use.

### Upload a file and link it in one go

The PDF from the venue, or a photo of the whiteboard, may not be in Initiative yet. You need to be able to make files in the initiative.

1. Select **Add link**.
2. Drop the file on the dialog, or select **Choose a file**.
3. Check its **Name**.
4. Pick how the two relate.
5. Select **Upload and link**.

The file lands in the initiative's Files, already linked. Dropping a file straight onto a **Connections** section opens the same dialog with the file already in it.

### Remove a link

Select the **×** on the link's card (**Remove the link to …**). Links that write themselves can't be removed this way; edit the words that make them.

## See what's blocking a task

A task waiting on something says so on the board and in the list, with a count of what's holding it up. The count only includes things that haven't finished, so when the blocker is done the mark goes away by itself. Nobody has to remember to tidy up.

| A blocker that's | Stops blocking when |
|---|---|
| A task | It reaches a done column |
| A project | Every task in it is done (an empty project hasn't finished anything yet, so it counts) |
| An event | It's over |
| A counter | It reaches its target |

Archived tasks sit out, so shelving a task doesn't keep its project open forever. A repeating event, a counter with no target, a file, a collection or a wiki page can sit under **Blocked by** if that's what you said, but nothing about them says when they're done, so they never add to the count.

## Look at connections another way

Pick how **Connections** shows them with the buttons beside its heading:

| View | Shows |
|---|---|
| **Carousel** | One row of cards to scroll through. Where most things start |
| **Tiles** | Cards under a heading for each kind of link |
| **List** | Rows under a heading for each kind of link. Where wiki pages start |
| **Graph** | Everything within one, two or three **Hops**, with **Show tags** to draw the tags things share |

Each thing remembers the view you picked for it on this device.

![A task's Connections shown as tiles, with cards under Attached, Blocked by, Blocking and Mentioned in, and Add link beside the heading](../images/tools/connections.webp#only-light)
![A task's Connections shown as tiles, with cards under Attached, Blocked by, Blocking and Mentioned in, and Add link beside the heading](../images/tools/connections.dark.webp#only-dark)
