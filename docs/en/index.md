---
icon: lucide/compass
---

# Welcome to Initiative

Initiative is where your group keeps its projects, tasks, files and plans, all in one place.

Right now they're probably spread across a group chat, two spreadsheets, an email thread from March, and the head of whoever has been doing this the longest. We know about the spreadsheet. We know somebody color-coded it in 2019 and nobody remembers what green means. It's going to be okay.

## Start small

One project with a few tasks on it is a complete setup. If you never touch another feature, you'll still be better organized than you were on Tuesday.

Everything else is already here and waiting: files, calendars, dashboards and the rest. None of it will interrupt you, and none of it will email you to ask whether you've considered optimizing your workflow.

[Start with Getting started](getting-started/index.md){ .md-button .md-button--primary }

## You cannot break this

This is the thing people actually worry about, so let's get it out of the way.

- **Deleted something?** It's waiting in the Trash, and you can put it back.
- **Dragged a task into the wrong column?** Drag it back.
- **Made an initiative you didn't need?** Archive it. It leaves the sidebar and nothing in it is deleted.
- **Made a project called "test"?** Everyone does.
- **Made four projects called "test"?** Somebody in your group has made five.

The few things you can't undo yourself, like deleting something from the Trash for good or deleting a whole community, ask before they happen, and the biggest ones want your password too.

So click around and open the menus. The worst thing likely to happen today is a slightly messy sidebar.

## The conversation stays with the work

In Initiative, the conversation about a task or a file happens in the comments on that thing. The next person finds it without being told where to look, and search finds it when somebody half-remembers it six months later.

A group chat goes differently. Somebody pastes the thing that should have been a document, and six months later everyone is scrolling for it, and Jenny has left, and somebody is looking at the printer in a way the printer has done nothing to deserve.

## Find what you need

<div class="grid cards" markdown>

-   :material-rocket-launch-outline: __Getting started__

    Make an account, find your way around, and join your group.

    [:octicons-arrow-right-24: Getting started](getting-started/index.md)

-   :material-sitemap-outline: __How Initiative is organized__

    Communities, initiatives and tools, and how they fit together.

    [:octicons-arrow-right-24: The big picture](concepts/index.md)

-   :material-book-open-variant: __Using Initiative__

    How to do things with projects, files, calendars and everything else.

    [:octicons-arrow-right-24: Using Initiative](guides/index.md)

-   :material-account-multiple-check-outline: __Sharing & access__

    Who sees what, and how to change it.

    [:octicons-arrow-right-24: Sharing & access](sharing/index.md)

-   :material-shield-lock-outline: __Security & privacy__

    How your group's work stays your group's.

    [:octicons-arrow-right-24: Security & privacy](security/index.md)

-   :material-cog-outline: __Running a server__

    Installing Initiative and looking after it.

    [:octicons-arrow-right-24: Running a server](running-a-server/index.md)

-   :material-help-circle-outline: __FAQ__

    Short answers to the things people ask most.

    [:octicons-arrow-right-24: FAQ](faq.md)

</div>

## Two ways to run it

You can host it yourself for free. It's open source and it's the whole product, and a ten-year-old laptop with a broken hinge makes a perfectly respectable server.

Or let us host it on Initiative Cloud and never think about a database again, which is a very reasonable thing to want. It's the same software either way. [Which one is you?](self-host-or-hosted.md)

## Why we built this

We're self-hosters. We got here the way most people do, by slowly going off the tools we relied on as it became clearer what they were doing with the things we put into them.

What tipped it was watching creative work get fed into AI training by companies that never thought to ask. We like AI and we use it, but being useful doesn't entitle anyone to take what somebody made. Once that's happened to something of yours, "we promise not to" doesn't sound like much of a promise.

So we treated it as a design problem rather than a policy, because a policy lasts only as long as the person who wrote it stays in charge. Nobody on a server's staff can open a community they don't belong to without a time-limited grant that leaves a record. Private messages are encrypted on the devices in the conversation, and those devices hold the only keys.

That means there's no pipe running from your work to anybody's model. The AI features Initiative has run only when you ask them to, on the thing you pointed them at, under the terms of whichever AI provider your server uses. See [AI features](account/ai-features.md).

## Two words with specific jobs

Initiative gives two ordinary words particular meanings, and we're sorry in advance.

- A **community** is one group's whole workspace. Your book club and your rec league team would be two separate communities.
- An **initiative** is a folder for one big effort inside a community, like this season's tournament.

And yes, the app is called Initiative too. The [glossary](reference/glossary.md) has the other words we've bent to our own purposes.

??? techspec "For the technically minded: what this actually is"
    Initiative is a React single-page app talking to a Python service (FastAPI) backed by PostgreSQL. Each community's content lives in its **own database schema**, so a request inside one community can't address another community's tables at all. The layers inside a community (which initiative, which role, which item) are enforced by PostgreSQL row-level security rather than by application code. There are apps for Android, Windows, Mac and Linux, and the web app installs from the browser, which is how it gets onto an iPhone or iPad. More in [Security & privacy](security/index.md) and the [server guide](running-a-server/index.md).

## Built in the open

Initiative is developed in public, and what people tell us shapes what gets built next. If something here is unclear, wrong or missing, say so on [GitHub](https://github.com/beyonders-studio/initiative). We do read it.
