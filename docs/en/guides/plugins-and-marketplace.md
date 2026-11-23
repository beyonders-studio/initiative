---
icon: lucide/store
---

# Plug-ins & the marketplace

Whatever your group needs, some other group has needed exactly the same thing, built it, got tired of rebuilding it every spring, and shared it. The **marketplace** is where those live: ready-made dashboards, projects and plug-ins you add in a couple of clicks, without anybody writing code.

Plug-ins are how Initiative grows. A tool that only some groups need comes as a plug-in, so each community has the tools it picked and none it would spend years scrolling past. [Counters](counters.md) is one: free, made by Initiative, and added from the marketplace by the groups that count things. What a plug-in can do widens with every release, so if you can picture one your group would use, [tell the team](help-and-feedback.md#send-feedback-to-the-team-that-makes-initiative).

Everything on your marketplace either ships with Initiative or was put there on purpose (see [where listings come from](#where-listings-come-from)). Nothing you add can reach past what you allow it, and you can take any of it back out.

There are two marketplaces, and the difference is who gets what you take:

| | **Your community's marketplace** | **Your own marketplace** |
|---|---|---|
| What's on it | Dashboards, projects and plug-ins | Home layouts and decoration packs |
| Who gets it | Everyone in that community | You, in every community you're in |
| Where to find it | **Browse the marketplace** in a Dashboards or Projects list, or at the bottom of the **Plug-ins** section of the sidebar | **Browse the marketplace** when making a new home view, or under **Your packs** in **My Settings → Profile** |

Every listing says who published it ("by Initiative", or the publisher's name) on its card, on its page and in the dialog where you add it, so you know before you decide.

## Add a ready-made dashboard { #adding-a-dashboard }

A marketplace dashboard is a screen of charts, numbers and timelines somebody already laid out. You can add one wherever you can create dashboards. If you can't, ask an initiative manager to give your role the dashboard permission (see [Initiative roles](../sharing/initiative-roles.md)).

1. Open an initiative's **Dashboards**.
2. Select **Browse the marketplace**. On a list that already has dashboards, it's under **More actions**.
3. Open a listing. **Preview** shows it drawn with sample data.
4. Select **Add to an initiative**.
5. Pick the **Initiative**.
6. Change the **Name**, if you like.
7. Select **Add**.

It shows up under that initiative's **Dashboards**, and from then on it's a dashboard like one you built: rename it, tag it, share it, delete it. It shows each person only the numbers they could already reach, so two people looking at the same dashboard can correctly see different totals.

When the publisher puts out a newer version, the dashboard shows something like **Version 1.3.0 available**. Anyone who can edit the dashboard can select it to update, and nothing changes until somebody does. A listing that needs a newer version of Initiative than your server runs says so rather than half-working.

## Copy a ready-made project { #adding-a-project }

Somebody has already worked out which columns a hiring pipeline needs. Initiative ships with a sales pipeline, a hiring pipeline, a bug tracker, a content calendar, a grant tracker, a product launch, facility maintenance and plant care. Each comes with [task types](project-setup.md#task-types) of its own, so the bug tracker has bugs, feature requests and chores, and plant care has watering, fertilizing and repotting.

You can add one wherever you can create projects.

1. Open an initiative's **Projects**.
2. Select **Browse the marketplace**. On a list that already has projects, it's under **More actions**.
3. Open a listing. **Blank** and **Example** show the empty board you'd get and the same board with made-up work moving through it.
4. Select **Add to an initiative**.
5. Pick the **Initiative**, and change the **Name** if you like.
6. Under **What to start from**, pick **Start blank** or **Start from the example**.
7. If it asks for a **Start date**, pick one. The project's dates move so the earliest lands on that day, and the rest keep their distance, so a launch six weeks out is still six weeks out.
8. Select **Add**.

What you get is an ordinary project of your own. Rename the columns, delete the example tasks, take it apart completely; nothing you do reaches the listing or anybody else's copy.

## What a plug-in can be { #kinds-of-plug-in }

A **plug-in** adds something to the whole community. They come in four kinds:

- **A tool**: a new kind of thing to keep in your initiatives, beside projects and files, that works like the built-in tools. Nothing runs anywhere for it; Initiative builds the tool from the plug-in's description. [Counters](counters.md) is one, and [Use a tool a plug-in added](#use-a-tool-a-plug-in-added) has the rest.
- **A page**: a page of its own in the sidebar, which can be another site shown inside Initiative or a whole application.
- **An integration**: a service your group already uses, brought in through an account you connect, with Initiative doing all the talking to it. [GitHub](github.md) is one.
- **A service**: a program its publisher runs beside Initiative that does what its listing says, like widgets for dashboards, [fields and buttons on your items](#what-a-plug-in-puts-on-items) or steps an automation can take.

You don't need to know which kind you're looking at. Each listing carries a tag saying how it shows up for the people using it (**New tool**, **Whole community**, **Own page**, **Connects an account** or **Adds to your tools**), and **What it adds**, under its description, names everything it brings.

## Add a plug-in to your community { #adding-a-plug-in }

Because a plug-in affects everyone, only your community's [superadmin](running-a-community.md#why-superadmin-is-separate) can add or remove one. Everybody else can browse, read the listing, and go ask them nicely.

1. In the community's sidebar, select **Add a plug-in** at the bottom of the **Plug-ins** section.
2. Open a listing.
3. Select **Add to community**.
4. Change the **Name**, if you like.
5. Answer the questions it asks (below).
6. Select **Add to community**.

It appears in the **Plug-ins** section of the sidebar, above your initiatives, and under the initiatives it works in if it has a page or a tool there. If it needs a credential or a setting before it can do anything, it's marked **Needs setup**; see [Managing plug-ins](managing-plugins.md).

The marketplace only offers plug-ins your server can run. Some need a program running alongside Initiative, so if you expected one and can't find it, ask whoever runs your server. Some listings also have a minimum age, shown as **Ages 16+** (or whatever it is where you are). The community can add it anyway; somebody under that age just can't open or use it.

### What you're agreeing to { #what-youre-agreeing-to }

Adding a plug-in asks up to four things, and every answer can be changed later from its settings, so you can't get any of it wrong in a way that sticks. A plug-in that asks for nothing just gets a name.

![The Add dialog for the Community calendar plug-in, asking only for its name](../images/marketplace/add-plugin.webp#only-light)
![The Add dialog for the Community calendar plug-in, asking only for its name](../images/marketplace/add-plugin.dark.webp#only-dark)

| Question | What it decides |
|---|---|
| **What it can reach** | What it may read, or read and change: projects, files, comments, tags, metadata, and so on. Everything it asks for starts ticked; untick what you'd rather it didn't have. A line marked **This server doesn't allow it** stays off whatever you tick. |
| **Where it works** | **Every current initiative**, or **Only the initiatives I choose**. It reads and changes things only in the initiatives it works in, so the committee's private budget initiative stays out of reach unless you put it there. For a tool, this is where the tool appears. |
| **Who can use it** | What the plug-in lets your community decide, like using it at all or seeing prices, and where each is changed: inside initiatives on each one's Roles screen, across the community on its Roles screen. Each says whether members start with it. Nothing to answer here. |
| **Plug-ins that can use it** | Only when plug-ins you already have ask to use this one. Each starts ticked. |

Some plug-ins work through another one, the way a plug-in that files bug reports might open them through a code-hosting plug-in. You're asked about that when the second plug-in arrives, so a community without the code-hosting plug-in is never asked whether anything may use it. Remove that plug-in and the permission goes with it; add it back and you're asked again.

A plug-in allowed to change something, a task say, can fill in that thing's [metadata](initiatives.md#metadata) too. Ticking **Metadata** itself lets it read the initiative's list of metadata fields, and with change allowed, add to that list and edit it.

However you answer, a plug-in never reaches past what you allowed. One that may read projects in the Garden initiative reads projects in the Garden initiative, and not files, and not the Kitchen.

### Letting a plug-in act as a moderator or an admin

On its own, a plug-in sees what any member of an initiative it works in would see: what's shared with everyone there, and what it made itself. Something shared with three people stays with those three.

Some plug-ins can do more, and ask in two lines that start unticked:

- **Act as a moderator in the initiatives it's placed in.** Inside an initiative it works in, it reaches everything a moderator would, whoever it's shared with.
- **Act as an admin across your whole community.** Everything a community admin reaches, including initiatives it isn't placed in.

Ticking one lets the plug-in use that standing when it needs to, not all the time. Either way it reaches only the kinds of thing ticked above, so an admin-standing plug-in that may read projects reads every project, and no files.

## Use a plug-in

Plug-ins are in the **Plug-ins** section of the community's sidebar. Select one to open its page. One with a page inside initiatives also shows up under each initiative it works in, for the roles that use it there. A plug-in that adds things elsewhere, like widgets or fields, has nothing to open, so it waits under the **2 more** (or however many) line at the bottom of the section.

Point at a plug-in in the sidebar and a gear appears beside its name. That opens its settings, showing the parts that are yours to decide.

### Connect your own account to a plug-in

Some plug-ins work with another service on your behalf, so each member signs in with their own account there. Nobody else sees yours, admins included.

1. Point at the plug-in in the sidebar and select its gear (or select its name, if it has no page).
2. Under **Your account**, select **Connect**.
3. Sign in to the other service in the tab that opens.
4. Close that tab when it says **Connected**.

The settings then say **Connected as** and your account there. **Disconnect** takes it back, and **Reconnect** fixes a connection that's **Expired**. Your community's superadmin can see who has connected and disconnect anybody, and if it says **A community admin has stopped you connecting this**, that's what happened.

### Let a plug-in act as you

A plug-in sometimes asks to do something in your name, like commenting on a linked issue as the person who closed it. It asks for each purpose on its own, in its own words, and you get a notification under **Waiting on you**.

1. Open the plug-in's settings from the gear beside its name.
2. Under **What it has asked to do as you**, read each request.
3. Select **Let it read as me**, **Let it read and change things as me**, or **Decline**.

You can change your mind any time: **Stop this** ends one you allowed. Nobody else can answer these for you, admins included.

### What a plug-in puts on items { #what-a-plug-in-puts-on-items }

Some plug-ins add to things you already work with: an invoice number on a task, a **Paid** tick on an event, a progress bar on the post announcing a fundraiser that's very nearly there. They can appear on tasks, calendar events and posts.

| | What you see |
|---|---|
| **Fields** | A labeled value drawn like Initiative's own: text, a number, a date, a link, a colored badge, a progress bar or a checkbox. A field can hold a list too, like every pull request linked to a task, each with its state. Task fields can be filtered on like any other. |
| **Sections** | A small panel on the item's page, made of the plug-in's fields and buttons. |
| **Actions** | A button in a section, an entry in the item's menu, or a button beside one entry in a list, that asks the plug-in to do something with this item. Some check with you first, or ask a question or two, like which repository. |

The plug-in keeps those values in Initiative, so they show and filter without waiting on it. They follow what the superadmin agreed to: a plug-in only marks items it may read, and only in the initiatives it works in, for the roles that use it there. A plug-in can keep some of its values and actions to a permission of their own, which each initiative gives to the roles it chooses.

Whoever looks after the initiative's layouts can move a plug-in's fields and sections, or take them off, in [Edit layouts](layouts.md). One taken off stays off, updates included.

## Use a tool a plug-in added { #use-a-tool-a-plug-in-added }

A tool from a plug-in sits in each initiative it's placed in, beside the built-in ones: under the initiative in the sidebar, and as a tab on the initiative's page. In an initiative it isn't placed in, it isn't there at all. Placing it is the superadmin's job; see [Change where a plug-in works](managing-plugins.md#change-where-a-plug-in-works).

Inside it, the tool works like a built-in one: the initiative's managers can [switch it off](tools.md#turn-a-tool-on-or-off-for-an-initiative) on the **Tools** card, and each role has **View** and **Create** for it on the [Roles screen](../sharing/initiative-roles.md#what-a-role-can-allow). Everyone starts able to open it, and making new things in it is up to the managers until a role is given **Create**. If there's no **New** button, that's why.

### Make something in a plug-in's tool

1. Open the initiative and select the tool's tab.
2. Select **New** and the thing's name, like **New Counter group**. (On a phone, it's the **+** at the bottom of the screen.)
3. Give it a name, and fill in whatever else you know.
4. Select the button at the bottom of the dialog, which carries the same name.

Each one has a page of its own, laid out the way the plug-in drew it. Each field saves as you change it. If the tool keeps things inside things (counters inside a counter group, say), they're listed on the page with a **New** button of their own.

When the tool has more than one way to show a list, the **Views** switch at the top picks between them, and **Presets** sorts it. Both are yours alone and change nobody else's screen.

### Run a plug-in's action

A plug-in can give its things buttons that do more than one field's worth of work, like **Reset All** in Counters.

1. Open the thing.
2. Select **Actions** (the **⋯**).
3. Pick the action. If it asks a question or wants a confirmation first, answer it and select the action's name again.

The menu is only there for people who can change the thing.

### What else a plug-in's tool does

It lives by the same rules as everything else in the initiative. Its things can carry comments and links, turn up in the community's search, can be charted on a [dashboard](dashboards.md), and go into a backup of the initiative or the whole community. A plug-in can also say when one of its things counts as finished, so a task [blocked by one](mentions-and-links.md#see-whats-blocking-a-task) waits until it is: a task blocked by a counter waits until the count reaches its max.

A plug-in's tool can also bring ready-made dashboards over its own things. Once the community has the plug-in, they're in the marketplace for each initiative to [add like any other](#adding-a-dashboard). Counters brings the **Counter board**: one counter as the headline, its progress toward the goal, and the rest of its group charted alongside. Like any dashboard, it shows each person only what they could already see.

## Report a listing or a plug-in

Something in a plug-in or listing that shouldn't be there? Tell whoever runs your server.

1. Open the listing's page, or the plug-in's own page.
2. Select **Report** (the flag) beside its name.
3. Pick what's wrong under **What is wrong?**, and add anything else they should know.
4. Select **Send report**.

It goes to whoever runs your server, not to the publisher, and not to your community's admins. Initiative's own listings carry no flag. If one of those misbehaves, that's a bug, so tell whoever runs your server the way you would about anything else that's broken.

## Your own marketplace { #your-own-marketplace }

Your own marketplace holds things for you rather than your community: **home layouts** and **decoration packs**. Whatever you take from it comes with you into every community.

### Add a home layout { #home-layouts }

A home layout is a ready-made page of widgets for a particular kind of day. It's only an arrangement: every widget reads your own tasks and calendar when it draws.

1. On **Home**, select **Customize**.
2. Select **+** beside your view tabs.
3. Select **Browse the marketplace** at the bottom of the picker.
4. Find a layout under **Home layouts**.
5. Select **Add to my home**.

It opens as a new view beside the ones you have, and nothing you arranged is touched. See [Your space](your-space.md#home) for arranging it from there.

| Layout | What's on it |
|---|---|
| **Week ahead** | The whole week on one page. |
| **Study session** | A timer, the next thing, and your streak. |
| **Stand-up** | What happened to your things, and what moved. |
| **Club secretary** | Your groups, their calendars, and what's been posted. |
| **Around the world** | Clocks for a team that's never all awake at once, and what changed while you slept. |

### Get a decoration pack { #decoration-packs }

Decoration packs are artwork for your profile, and by far the least serious part of Initiative. Each is built around something a group of people has in common (Sports, Drama, Pets, Tea, Spooky and plenty more) and carries banners, frames and trophies to wear in any combination you like. Plenty of the banners move: skeletons dance, a lake changes color as the sun goes down into it, and the view from a train window keeps going past.

1. In **My Settings → Profile**, select **Browse the marketplace** under **Your packs**.
2. Under **Decoration packs**, open a pack to see everything in it.
3. Select **Get this pack**.

Its pieces land in your collection, and nothing goes on you until you choose it. Pick what to wear back in **My Settings → Profile**, mixing pieces from different packs however you like; see [Profile & preferences](../account/profile-and-preferences.md#decorations). A pack's banners can also go on your [home views](your-space.md#put-a-banner-on-a-view).

To give a pack back, select **Remove pack** on it, here or under **Your packs**, and confirm. Its pieces leave your collection, and anything from it you were wearing comes off.

## Where listings come from

Every listing on your marketplace arrived one of three ways:

- **It ships with Initiative.** It's credited "by Initiative", and nothing else can claim that credit.
- **It came from the Initiative registry,** a signed online catalog your server follows unless whoever runs it has switched it off. Anyone can propose a listing for it, and it's published once it's been reviewed. Every file from it is checked against a signing key built into Initiative before anything is used, so a listing arrives exactly as it was published or not at all.
- **Whoever runs your server added it.** If you run Initiative yourself, that's you; see [Publishing your own listings](../running-a-server/publishing-listings.md).

Marketplace widgets on dashboards run in a sandbox that can only hand back something to draw. If one misbehaves, that tile shows an error and the rest of the page carries on.

### On the iPhone app

The iPhone app's marketplace shows the listings that ship with Initiative and the ones from the Initiative registry. Anything whoever runs your server added themselves is browsed from the website or the other apps.

Plug-ins your community already has open as usual. The first time you open one that doesn't come from Initiative, you're told who made it, that your community and its publisher provide it, and where to report it. Select **Continue**, and it won't ask again for that plug-in.
