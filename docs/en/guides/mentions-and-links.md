---
icon: lucide/at-sign
---

# Mentions & links

Work refers to other work. A write-up explains a project. A comment asks about a task. A plan points at the rota that feeds it.

Three characters handle all of that:

| You type | You get |
|---|---|
| `@` | A person, and they get told |
| `#` | A link to anything that already exists |
| `[[ ]]` | A link to a tool — and it'll create one that doesn't exist yet |

All three work in every **comment**, on every tool, in a task's **description**, and inside any **text document**.

## `@` — mentioning a person

Type `@` and a few letters of somebody's name, pick them from the list, and they get a notification. It's the right way to say "can you look at this."

You're offered the people in the same initiative, and somebody hears about it only if they can open the thing you're writing in. A mention that summons somebody to a page they can't open helps precisely nobody, so share the thing with them first.

Names match loosely, so a spelling you're not confident about will still find the right person.

In a task's description, a person hears about it once — when their name goes in. Rewording the sentence around them later doesn't ping them again, which they will appreciate more than they'll ever say.

A mention shows the name the person goes by today — their display name in this community, or their handle — wherever it appears, so it keeps up when they change it. Somebody who has left the community, or whose account was erased, reads as **Former member**.

Searching for that name or handle finds what mentions them, even mentions written before they changed it. Type it in whole words.

## `#` — linking to a thing

Type `#` and Initiative offers you everything in the initiative: every [tool](tools.md), and what's inside them — tasks, events, counters, queue items, pictures, wiki pages. Pick one and its name drops into your text as a link.

Already know what kind of thing you want? Say so and the list narrows: `#task:`, `#file:`, `#project:`, `#queue:`, `#counter-group:`, `#calendar:`, `#dashboard:`, `#post:`, `#collection:`, `#wiki:`, `#wiki-page:`.

You never *have* to. `#` on its own searches the lot — the prefixes are just a shortcut for when half the community has named something "Planning".

Mentioning a task also notifies whoever it's assigned to.

The list reaches the work in **this initiative** — the document's own, if you're writing in one — so a community absolutely stuffed with matching tasks can still come back with nothing.

When that happens the picker says so, and explains that the initiative is the limit, rather than leaving you staring at an empty box slowly retyping the same word.

!!! tip "Links survive renames"
    A `#` link points at the *thing*, not at its name. Rename a task and the sentence mentioning it quietly updates itself.

## `[[ ]]` — linking, or conjuring

`[[` offers the **[tools](tools.md)** in this initiative.

The difference from `#` is what happens when nothing matches. `[[ ]]` offers to **make** the thing you just named, on the spot, without you abandoning the sentence you were halfway through.

That's why it reaches tools and `#` reaches everything. A tool needs only a name and the initiative you're already standing in. A task needs a project, and an event needs a calendar and a time — you can't summon those out of a half-written sentence, so reach them with `#`.

A tool your initiative has switched off isn't offered, and can't be created this way either.

Everything you point at keeps a list of what points back, under **Mentioned in** in its [Connections](#connections), so you can see what refers to a page without keeping a list yourself. A `#` link counts, not just a `[[ ]]` one, and so does a [smart chip](files.md#smart-chips) or an [embed](files.md#embeds). A page pointing at itself doesn't.

In a text document, a `!` in front — `![[` — shows the thing in full instead of linking to it. See [Embeds](files.md#embeds).

## Names look after themselves

A reference points at the thing, not at its name. Rename a task and every sentence mentioning it says the new name — in every document and every comment, with nobody editing anything.

If what you pointed at gets deleted, or was never shared with you in the first place, the reference keeps the words it was written with — greyed out, no longer a link.

It never claims something you can't see doesn't exist, and it never leaves a hole in the middle of a sentence for you to puzzle over.

!!! note "Exports show the words"
    A PDF or Word file can't keep itself current, so an export shows the name a thing had when the reference was written.

!!! note "`#` and `@` aren't allowed in names"
    Both already mean something when you're writing, so a name or title can't contain either. Initiative tells you rather than quietly creating a reference nobody can follow.

## Going further than a link

Inside a text document, a **smart chip** shows what a thing is currently *doing*, not just what it's called — a task's column, an event's date, a counter against its target, a project as **1 / 3** of its tasks done. See [Files](files.md#smart-chips).

The same readings show up on anything you've linked, so a relation is never just a name.

## Connections

A `#` link says *that* two things are connected. A **relation** says *how*.

Every tool has a **Connections** section, and so do the things inside one — a
task, an event, a picture, a wiki page. It lists what this thing links to as
well as what links to it. Add a link and you get a sentence with both names in
it:

> **This task** *is blocked by* **Order the marquee**

Find the thing first. The wording is a dropdown in the middle, and you can
change it after — so you never have to know the vocabulary before you start
typing.

If the thing isn't in the app yet — a PDF, a photo of the whiteboard — upload
it right there instead. Choose a file, or drag one onto the panel, and it
lands in Files in the same initiative, already linked. You need to be
allowed to make files in that initiative to see the option.

| Heading | What it means |
|---|---|
| **Attached** | The files this runs on |
| **Blocked by** | What has to happen first |
| **Blocking** | What's waiting on this |
| **Part of** | The bigger thing this belongs to |
| **Made up of** | The pieces it's built from |
| **See also** | Related. No stronger claim than that |
| **Links to** | Everything this points at |
| **Mentioned in** | Everything pointing here |

**Links to** and **Mentioned in** write themselves — they're the `#` and
`[[ ]]` links above, read from what's written. Edit the words and they follow.

### "Blocked by" earns its keep

A task waiting on something says so on the board and in the list, and the count
only counts the things that haven't finished. Mark the blocker done and the
mark goes away on its own. Nobody has to remember to tidy up.

What counts as finished depends on what it is:

| | Stops blocking when |
|---|---|
| A task | It reaches a **Done** column |
| A project | Every task in it is done — an empty one hasn't finished anything yet, so it still counts |
| An event | It's been and gone — a repeating one never counts, having no last time |
| A counter | It reaches its target |

Archived tasks sit it out, so shelving something doesn't keep a project open
forever.

Anything else — a file, a collection, a wiki page — still shows up as a link,
and still sits there under **Blocked by** if that's what you said. It just
isn't counted, because nothing about a file says when it's done.

!!! tip "Four ways to look at it"
    **Carousel** (a row of cards to scroll through) is where most things
    start, and wiki pages start on **List**. There's also **Tiles**, and
    **Graph**: everything within a hop or a few, with **Show tags** to draw
    the tags things share. Pick one and that page keeps it.

## Related

- [Files](files.md) — including smart chips.
- [Search & shortcuts](search-and-shortcuts.md)
- [Notifications](notifications.md)
