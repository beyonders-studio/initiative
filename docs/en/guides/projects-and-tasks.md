---
icon: lucide/clipboard-check
---

# Projects & tasks

A **project** is a board for tracking work. **Tasks** are the to-dos on it.

If you only ever learn one part of Initiative, make it this one. It's where basically everything happens.

## Making a project

1. Open the initiative it belongs in and click **Add Project**.
2. Fill in:
    - **Name** — the only required bit.
    - **Icon** — an emoji, so you can find it at a glance.
    - **Description** — optional.
    - **Initiative** — which folder it lives in.
    - **Template** — optionally start from one you saved earlier (see [Templates](#templates)).
3. Create it. The board opens, empty and radiating potential.

![Creating a project](../images/projects/create-project.png)

The top of the project shows how far along it is and its dates, beside its status, tags and metadata — the same [header every tool has](tools.md#the-top-of-every-tool-page).

### Bookmarks, pinning and your own order

Both live on each project's card.

- **Bookmark** puts it in your **Bookmarks** in the sidebar and on Home. Just for you: bookmarking something doesn't inflict it on anybody else. Every other tool has the same bookmark; see [Bookmarks](your-space.md#bookmarks).
- **Pin project** marks it as pinned for everyone in the initiative. That one takes a project manager.

Drag projects on the first page of the list to put them in your own order.

## Adding tasks

Click **Add task**. Only the **title** is required, unless the task type says otherwise: a type's page can [require fields](layouts.md#required-fields), and those sit up top in the dialog until they're filled. Everything else is in the same dialog, laid out exactly as the task will be once it exists, so there's one layout to learn instead of two. Fill in what you know. The rest can wait, possibly forever, and nothing will nag you about it.

Nothing is saved until **Create task**. Close the dialog and it's gone.

Once a task exists there's no Save button at all: each field saves the moment you change it. A description keeps a draft while you write, and if somebody else edited it meanwhile, you're shown their version before yours goes over it. People who can't edit a task see its values, not a wall of greyed-out boxes.

A task can hold:

| Field | What it's for |
|---|---|
| **Title** | A short name. Required. |
| **Description** | The detail. Formatting works, with a **Preview**, and so do `@`, `#` and `[[ ]]` — see [Mentions & links](mentions-and-links.md). Paste or drag in a screenshot and it lands where your cursor is; take it back out and it's gone from storage too. |
| **Status** | Where it's got to. |
| **Priority** | Low, Medium, High, or Urgent. |
| **Start date** | When work should begin. |
| **Due date** | When it's due. Optional, and you don't have to be brave about it. |
| **Assignees** | One person or several. |
| **Checklist** | The smaller steps, ticked off, with a progress count. |
| **Tags** | Labels for finding things later — see [Tags](tags.md). |
| **Recurring** | Make it come back on a schedule. |
| **Metadata** | Your initiative's own fields — see [Metadata](initiatives.md#metadata). |
| **Properties** | Fields only this project's tasks have — see [Project properties](#project-properties). |

![Editing a task's details](../images/projects/task-details.png)

### Typing the details into the title

A new task's title fills in the rest as you type. "Email the caretaker about the hall keys friday at 3pm !high #fete @sam" becomes a task called "Email the caretaker about the hall keys", due Friday at three, high priority, tagged fete and given to Sam.

| Write | And it sets |
|---|---|
| `today`, `tomorrow`, `friday`, `next friday`, `next week`, `in 3 days`, `oct 30` | The due date. On its own, a date is due by the end of that day. |
| `at 3pm`, `9:30am`, `17:00`, `noon` | The time it's due. A time with no date is today's, or tomorrow's if today's has already gone. |
| `every day`, `every other week`, `every 3 months`, `every mon, wed and fri`, `every weekday`, `every weekend` | A repeat, starting on the next day it falls on. |
| `every third tuesday`, `the last friday of every month`, `every 1st and 15th`, `every last day of the month`, `every last weekday of the month`, `every oct 30` | A repeat by its place in the month or the year. |
| `every! 6 weeks`, `ev! month`, `every 4 hours` | A repeat counted from when you finish each one, so the haircut is due six weeks after the last haircut, not six weeks after you first wrote it down. `ev` is short for `every`. Hourly repeats always count this way. |
| `until dec 18`, `10 times`, after any of the above | When the repeat stops. |
| `!urgent`, `!high`, `!medium`, `!low`, or `!1` (urgent) to `!4` (low) | The priority. |
| `#name` | A tag the community already has. `#bug-fix` finds "Bug fix". |
| `@name`, `@me` | Somebody who can open the project. Type `@` and a list of them opens, so you never have to remember how Sam spells their handle. |

A repeat it can't set up properly isn't set at all, and its words stay in the title. Every third second of the month, for one.

Whatever it reads is highlighted in the title and listed underneath, and the fields in the dialog show it too, so you see exactly what you're getting before **Create task**. Take a chip off the list and its words stay in the title as you typed them, for the day you really do need a task called "Plan next week". Delete the words and the field goes back to how it was.

It reads the language you've set the app in, and works in the home page's quick add box too. Rather your titles stayed exactly as typed? Switch off **Read details from the title** in [Preferences](../account/profile-and-preferences.md#preferences).

### Statuses

Every project starts with three:

**To Do → In Progress → Done**

You can rename them, add your own, and give each one an icon and colour, from **Project settings → Task statuses**. Each one still belongs to one of four underlying stages — Backlog, To Do, In Progress, Done — which is how "archive done tasks" knows what counts as done. Backlog is there if you want a holding pen ahead of To Do; new projects just don't start with one.

Delete a status you don't want and its tasks move somewhere sensible — you pick where, or let them fall to the project's default. The only one you can't delete is the last one standing.

### Task types

A task can be one of several kinds of thing, and each kind gets its own page. Every project starts with four, named in the language of whoever made the project:

| Type | For | Its page leads with |
|---|---|---|
| **Task** | Something to get done. The default. | The usual: description, checklist, everything. |
| **Bug** | Something broken. The leaky tap, the crashing spreadsheet, the hall door that only opens if you lift it. | How urgent it is, and what it's holding up. |
| **Idea** | Something worth talking about before anyone commits to it. | The description and the conversation. No dates, no checklist, no pressure. |
| **Milestone** | A date everything else is aiming at. | When it is, and what's still in the way. |

Pick the type when you add a task, or change it later from the **Type** field on the task. Changing it keeps everything the task holds: a date the new page doesn't show is tucked away, not deleted, and comes back if you change your mind.

Add, rename, reorder and recolour types from **Project settings → Task types**. **Add type** opens a shelf of ready-made ones, grouped by what they're for:

| | |
|---|---|
| **Planning** | Milestone, Event, Appointment |
| **Around the house** | Chore, Errand, Bill |
| **Groups and volunteers** | Volunteer shift, Purchase, Question, Idea, Request |
| **Making things** | Bug, Feature, Art, Playtest note |
| **Learning** | Assignment, Reading |

Each is a suggestion, name included: pick **Event** and call it **Gig**. Some bring fields of their own, like a Purchase's **Cost** and **Link** or an Event's **Location**. They're added to the initiative (or reused if it already has one by that name) and placed on the type's page. You can also start blank, or from one of the project's own types, which copies its look and its page.

A band might add **Gig** and **Song**; a household, **Chore** and **Bill**. Deleting a type moves its tasks to another one you pick, so nothing goes missing. The project's last type stays.

**What a new task starts with.** A type can fill in a new task's empty fields: a description outline, checklist lines, a priority, a repeat. A Bug starts with "what happened / what should have happened / how to make it happen again", a Chore repeats weekly and a Bill monthly. Change any of it from **Starts with…** on the type. When you make a task, the outline and priority are already filled in, and they change with the type you pick until you change them yourself. Anything you type yourself wins, and a repeat only starts on a task with a date to count from.

**Same types, several projects?** **Copy from another project** brings over the types you pick, with their pages and what they start with. One whose name the project already has is skipped. Project templates bring their types along anyway.

**A field just for one type.** While editing a type's page in **Edit layouts**, **Add a new field** makes the field and places it in one go.

Board cards show each task's type as its icon. Lists filter and group by type, too. And if you trim a project down to one type, types vanish from view entirely, because a label every task shares tells you nothing.

### Checklists

Break a big task into steps. As you tick them off, the task shows its progress — "3/5 items" — which is more motivating on a bad Tuesday than it has any right to be.

Enter starts the next line. Paste a list and you get one item per line, which saves a surprising amount of your life.

Good for the tasks that are secretly three tasks wearing a coat.

### Subtasks

When one of those steps turns out to need its own person, its own deadline and its own opinions, click the arrow on its line: **Make it a task**. The line leaves the checklist and comes back as a whole task in the same project, **Part of** the one it came from. A ticked line arrives done.

A subtask is a task like any other. It has an assignee, dates, a status and comments, and it turns up in calendars and **My tasks**. Its parent counts how many of its subtasks are done ("2/7 subtasks"), so you can see how far a post has got without opening it.

To put an existing task under another, link it as [**Part of**](mentions-and-links.md#connections) it, from the task's links or by dragging on the [Gantt](#gantt).

### Recurring tasks

For the things that keep coming back: the weekly report, the monthly review, the bins.

Pick the rhythm — hourly after completion, daily, every weekday, weekly, monthly, annually, or **Custom…** for the second Tuesday, the last weekday of the month and their friends. For **On schedule** repeats, the next few dates are listed under the form.

Finishing one makes the next, so there's only ever one to deal with. The strategy decides its date:

| | |
|---|---|
| **On schedule** | Counted from the dates. Pay the rent on the 1st, even if last month's went in on the 9th. |
| **After completion** | Counted from when you finished. Water the plants a week after you last did, not a week after you meant to. |

For a routine that needs a gap after each completion, choose **Hourly (after completion)**. This uses **After completion**: finishing a task makes the next due the selected number of hours later. **On schedule** tasks repeat daily or less often. Hourly completion times are counted to the minute.

Optionally set **Maximum per day**. Leave it empty for a continuous hourly repeat. With a maximum, reaching it or having the next repeat cross midnight moves the next task to the following day at the first task’s time, delayed when needed to preserve the gap. Set the first task’s due date and time to establish the starting time. The daily count and time are worked out from the series’ tasks in the timezone of whoever completes the task, so teammates can finish it in their own local day.

For example, with a maximum of three per day and a four-hour interval, completing the first at 09:30 makes the next due at 13:30. Finishing that one at 14:00 makes the third due at 18:00. After the third completion, the next reminder resumes the next day using the first task’s time, subject to the gap.

Missed days create no backlog. Skipping does not record a completion. Future dates for **After completion** repeats appear as tasks are created, because later dates depend on actual completions.

Upcoming dates show on calendars too, and open the task you're on now.

To change the repeat or stop it, edit the current task. That counts from here on, and the finished ones are left alone.

#### Changing one of them

Edit or delete a repeating task and Initiative asks which ones you mean:

| | |
|---|---|
| **Just this task** | This one changes. The next comes back the way the series was. |
| **Tasks after this point** | This one and every one after it. |
| **All tasks in the series** | Every one, finished ones included. It reaches the title, description, priority, assignees and tags. Dates stay each task's own. |

Dragging a repeating task on a calendar or the [Gantt](#gantt) asks too, minus the last option.

**Skip this occurrence**, in the task's menu, moves it on to its next date without finishing it. That's the week the bins weren't collected because of the bank holiday. Deleting just this task does the same, so the series carries on — unless it was the last one, in which case it's simply deleted.

Deleting from here on ends the repeat. Deleting all of them sends the finished ones to the trash as well, where they can be recovered.

### The bit where you get confetti

Finish a task that's assigned to you and Initiative marks the occasion — confetti, a "+1 Heart", a "Natural 20", or a shower of gold coins.

Pick your preferred celebration in **My Settings → Preferences**, or set it to **None** if you'd rather your accomplishments passed in dignified silence.

There's optional sound and vibration too, for anyone who wants the full experience. No judgement. Some weeks you need the coins.

## Four ways to look at a project

The same tasks, four ways of looking at them: a table, a board, a Gantt and a calendar. A new project shows just its board, which is plenty for most things. Switch the others on in **Edit layouts**, under [Layouts](#layouts), and the switcher at the top of the project offers them. Switch off the ones nobody uses, as long as one stays on.

Switching changes nothing about the tasks themselves — only what's on your screen — so there's no wrong choice here and nothing whatsoever you can break by trying one.

![Switching between task views](../images/projects/view-switcher.png)

### Table

A spreadsheet-style list. One row per task, with columns for status, priority, dates, assignees and whatever else the project's [layout](#layouts) adds.

**Best for:** scanning a lot of tasks, sorting, and editing several at once.

- Click a column heading to **sort** by it. Hold ++shift++ and click another to sort by both.
- **Group** rows by any field whose values repeat: date window (Overdue, Today, This Week, This Month, Later), status, priority, assignees, tags, who created it, or any select, person or checkbox metadata or property. Dates group by day, week, month, quarter or year. Each group says how many tasks it holds.
- **Filter** down to exactly what you want.
- **Select** several rows and edit them together.
- **Assign to me** in the **Assignees** column takes a task without opening it. Missing the column? Add it in **Edit layouts**.
- [Subtasks](#subtasks) sit under their parent, indented, and fold away with the arrow beside it.

![A project in Table view](../images/projects/view-table.png)

### Board

Cards in columns, one column per status. Drag a card along as the work moves.

**Best for:** seeing the shape of what's happening, and moving things along without opening a single dialog.

- **Drag and drop** between columns to change status.
- **Collapse** a column you're deliberately not thinking about.
- **Group** the board too, and each group becomes a band across the columns: one per person, say, or per priority.
- Group by **Parent task** and every task with subtasks gets a band of its own, holding it and its subtasks across the columns. Drag a card into another band and it becomes part of that task instead.
- A card's menu assigns you, unassigns you, or moves the task to another column.
- A column with a **limit** counts its open tasks against it in its header ("4 / 5"). Once it's full, nobody can add a task to it or move one in until one leaves. What's already there stays.

What a card shows is up to the project's [layout](#layouts). Take off what this project doesn't use and the cards get shorter and quicker to read.

![A project in Kanban view](../images/projects/view-kanban.png)

### Gantt

Each task is a bar from its start date to its due date, on a timeline you scroll sideways. A task with one date is a diamond on that day. A task with no dates gets an empty row, waiting patiently.

**Best for:** planning, seeing what has to finish before what, and noticing the Thursday onto which you have cheerfully scheduled six deadlines.

Moving things:

- **Drag a bar** to move the task, or drag one end to change just that date. Move a task later and the tasks waiting on it are offered the same move, all the way down the line, so a slipped delivery doesn't leave six tasks starting before it arrives.
- **Drag across an empty row** to give a task its dates.
- **No mouse?** The rows take the arrow keys: up and down to move, right and left to open and fold a task's parts, **Enter** to open one, and **Alt** with left or right to move it a day. Add **Shift** and only its due date moves.

What depends on what:

- **Arrows** run from a task to the ones [blocked by](mentions-and-links.md#connections) it. An arrow turns red when a task starts before the thing it's waiting on is done, which is your cue to have a word with somebody. Click one to take the link back.
- **Drag from the dot** at the end of a bar onto another task's row, then pick whether that task waits on this one or is part of it.
- A task's **parts** (the tasks that are **Part of** it) sit under it and fold away with it. The thin line over its row shows how far they stretch.
- **Critical path** fades everything but the chain that decides when the work finishes. Shorten that chain and the project ends sooner; shorten anything else and it doesn't.
- Tasks in **other projects** that yours are linked to sit in a band at the bottom, with their arrows. You can open them from here, but not move them.

And the rest:

- A **repeating task** shows its next few dates as dashed outlines along its row.
- **Day**, **Week** and **Month** set how much fits on screen. **Today** brings you back.
- **Group** it like the board, and each group gets a band of its own.

The initiative's [calendar](calendar.md) shows the same dated tasks by month, week or day, beside everybody's events.

![A project in Gantt view, grouped by assignee](../images/projects/view-gantt.png)

### Calendar

Your tasks laid out by their start and due dates, by month, week or day. A task with no dates doesn't appear, which is the point and also the catch.

**Best for:** a project whose work all happens on dates. Drag a task to another day to move it.

### So which one?

No wrong answer. A rhythm that works for most people:

- **Board** day to day, for nudging things along.
- **Table** when you're tidying up, sorting, or editing a lot at once.
- **Gantt** when you're planning ahead, or working out how bad next week is going to be.
- **Calendar** when every task has a date and the question is only ever "when".

Your choice is yours alone, and it follows you to any device, along with your filters, sort, grouping and columns. Until you pick, the project opens on whichever one its layouts say.

## When a board gets busy

- **Filter** by status, priority, assignee, due date and more.
- **Sort** by any column. In Table view, hold ++shift++ and click more columns to sort by several at once.
- **Group** by a field, and drag a task into another group to change that field. A task with two people or two tags is listed under each, and dragging it moves it out of only the group it came from.
- **Select several tasks** and act on them together — status, dates, assignees, priority, tags, or archive, all in one go.

!!! tip "Archive things, don't delete them"
    Finished tasks don't need deleting. **Archive** sweeps them off the board while keeping the record — there's a one-click **Archive done tasks** for the end of a push.

    And you can filter them back into view any time you'd like documentary evidence of how much you actually got done, which is useful when somebody asks and also just nice.

## Layouts

Each of the project's four lists has a layout, and so does a task:

| Layout | What it decides |
|---|---|
| **Table** | Which columns, in what order. |
| **Board** | What a card holds: priority, dates, tags, the checklist and subtask bars, the task it's part of, comment and blocker counts, any metadata or property. And each column's limit. |
| **Gantt** | Only its presets and groupings. Bars are bars. |
| **Calendar** | Only its presets. A calendar is a calendar. |
| **Task pages** | Where everything sits when a task is open, and in **Create task**. One per [task type](#task-types), each starting from a shape that suits it. |

Each list also offers **presets** in **Filters** — **Incomplete**, **Unassigned** and **Mine** to start with. Picking one sets your filters; it doesn't change anybody else's. It also goes in the page's address, so the link opens the list with it picked.

Each list can be **shown in the layout menu** or not, in the editor or straight from **Project settings → Layouts**, where the views and the task pages are listed apart. A new project shows all four; at least one list always stays shown, and the project opens on one of those.

The table, board and Gantt also say what you can group by, what they start grouped by, and which groups they leave out (finished sprints, for instance).

Change any of it from **Project settings → Layouts → Edit layouts**. That's for the project's owner, its initiative's managers and community admins; everybody else sees the result. See [Layouts](layouts.md) for the editor.

## Project settings

- **Details** — icon, name, description, dates, tags.
- **Access** — who can see or edit it. See [Sharing](../sharing/sharing-projects-and-files.md).
- **Layouts** — how its lists and tasks are laid out, and which list it opens on. See [Layouts](#layouts).
- **Task statuses** — your workflow.
- **Task types** — the kinds of task the project holds, and a shortcut to each one's page. See [Task types](#task-types).
- **Properties** — fields of the project's own. See below.
- **Advanced** — save as a template, [duplicate](tools.md#duplicating) it here or into another initiative, export, archive, delete.

### Project properties

Some things only matter in one project. The sprint a bug landed in. Which van the delivery goes on. Nobody planning the summer fete needs a "Van" box on their tasks, so it doesn't belong to the whole initiative.

That's a **property**: a field that belongs to the project and turns up on its tasks alone. Make one in **Project settings → Properties**, or from **Add** in the [layout editor](layouts.md), which asks whether a new field is the project's property or the initiative's [metadata](initiatives.md#metadata). Properties take the same types metadata does.

Rename, reorder or delete them in the same settings tab, or in the editor: click the layout's name at the top of its outline and the project's properties are listed on the right, each saying which layouts show it. Whoever can edit the project can change its properties. [Initiative settings → Metadata](initiatives.md#everything-in-one-place) lists them too, beside every other project's.

### Moving a task to another project

You can move a task from its menu. One thing that catches people out: because every project can have its own statuses, a moved task restarts at the new project's default status. Its type comes along if the new project has one with the same name, and becomes that project's default type if not. Each of its properties keeps its value wherever the new project has a property with the same name and type, and the rest are dropped.

Nothing's broken and you haven't lost anything. Set the new status and carry on.

### Duplicating a task

**Duplicate task**, in the task's menu, makes another beside it with "(Copy)" on its name, keeping its links to other tasks. Its checklist comes across unticked, because the copy hasn't done any of it yet.

## Templates

Set a project up exactly how you like it, then make it a **template** — from **Status** at the top of the project, from **Project settings → Advanced**, or by ticking **Save as template** when you create one.

Next time, start *from* it and skip the fiddling. Its checklists arrive exactly as the template has them, ticks and all; duplicating an ordinary project starts them over. Ideal for anything you do more than once: every new client, every event, every production. Nobody forgets the step at the end, because the step at the end is already there.

## Exporting a project

**Export a project** to a portable file — an offline copy, a move somewhere else, or a backup of one specific project. It imports back in later. It's in **Project settings → Advanced**, next to deleting it, and it belongs to the same people: whoever owns the project, and anyone who can see everything in its initiative.

The file carries the project's [layouts](layouts.md) as well, so it imports back in looking the way you left it. Plug-ins belong to a community, so they stay behind; wherever the file lands, the plug-ins placed in that initiative show up on it as they would on any project. A preset that picks out particular people or tags arrives without them.

The task list has an **Export** of its own: the tasks you've filtered to, or the ones you've selected, as a PDF, a spreadsheet or Markdown. It comes out the way you're looking at it, in your sort and your grouping, minus any groups the layout leaves out. Grouped by tag, a task with two tags turns up under both, same as on screen. The columns are the table's, properties included, and the detailed PDF follows the task page from top to bottom, so rearranging the layout rearranges the printout.

!!! note "People are named by handle"
    An export identifies assignees, event attendees and person-type fields by **handle** (`foobar#1234`), because a handle is the same in every community and an email address isn't.

## Archiving and deleting

- **Archive** hides a finished project without losing anything. Unarchive whenever.
- **Delete** sends it to the community **Trash**, where an admin can restore it until the retention period runs out.

## Related

- [Mentions & links](mentions-and-links.md#connections) — saying a task is blocked by another.
- [Tags](tags.md) — labelling and filtering.
- [Your space](your-space.md) — all your tasks, from every project and community at once.
