---
icon: lucide/settings-2
---

# Setting up a project

Every project works out of the box, with three statuses, four kinds of task and four ways to look at them. This page is for when you want it to fit your group better: your own workflow, your own kinds of task, your own fields, and a template so next time you don't have to do any of it again. Making a project and working on its tasks is on [Projects & tasks](projects-and-tasks.md).

Most of this happens under the project's **Settings**, at the top right of the project. Anyone who can edit the project can change what's on this page, except where a section says otherwise.

## Rename a project or change its dates

1. Open the project and select **Settings**.
2. On the **Details** tab, change the name or the description.
3. Select **Save**.

The **Icon (optional)**, **Start date** and **End date** below them save as soon as you change them. You can also rename a project by selecting its name at the top of the project.

## Change a project's workflow { #statuses }

Every project starts with three statuses: **To Do**, **In Progress** and **Done**. Each one belongs to one of four stages (**Backlog**, **To Do**, **In Progress**, **Done**), which is how **Archive done tasks** knows what counts as done. Backlog is there if you want a holding pen ahead of To Do.

### Add a status

1. Open the project and select **Settings**.
2. Select the **Task statuses** tab.
3. Under **Add status**, type a name.
4. Pick its category, and an icon and color if you like.
5. Select **Add**.

### Rename, recolor or reorder statuses

1. On the **Task statuses** tab, change the name, category, icon or color in the table, or drag a row by its handle.
2. To choose where new tasks start, select the circle in the **Default** column.
3. Select **Save changes**.

### Delete a status

1. On the **Task statuses** tab, select the bin icon on its row.
2. Under **Move tasks to**, pick where its tasks should go, or leave it to the project's default status.
3. Select **Delete**.

The project's last status can't be deleted, because a board needs somewhere to put a task.

## Give a project its own kinds of task { #task-types }

A **task type** says what kind of thing a task is, and each type gets its own icon, color and page. Every project starts with four, named in the language of whoever made the project:

| Type | For | Its page leads with |
|---|---|---|
| **Task** | Something to get done. New tasks start as this one. | The usual: description, checklist, everything. |
| **Bug** | Something broken: the leaky faucet, the crashing spreadsheet, the gym door that only opens if you lift it. | What needs fixing, and how urgent it is. |
| **Idea** | Something worth talking about before anyone commits to it. | The description and the conversation. |
| **Milestone** | A date everything else is aiming at. | Its dates. |

Choose a task's type when you add it, or change it later with its **Type** field. Changing it keeps everything the task holds: a value the new page doesn't show is tucked away, not deleted, and comes back if you change your mind. If the new type's page requires fields the task leaves empty, Initiative asks for them first.

Board cards and table rows show each task's type as its icon, and lists filter and group by type. Trim a project down to one type and types vanish from view entirely, because a label every task shares tells you nothing.

A project holds up to 20 types.

![The Task types tab, with the four starting types and their Edit page buttons](../../images/releases/task-types.webp)

### Add a type

1. Open the project and select **Settings**.
2. Select the **Task types** tab.
3. Select **Add type**.
4. Pick a ready-made type, **Blank**, or one of the project's own types under **Or start from one of this project's types**.
5. Change the **Name** if you like.
6. Select **Add**.

The ready-made types come in groups, and each is only a suggestion. Pick **Event** and call it "Game", and nobody will ever know.

| Group | Types |
|---|---|
| **Planning** | Milestone, Event, Appointment |
| **Around the house** | Chore, Errand, Bill |
| **Groups and volunteers** | Volunteer shift, Purchase, Question, Idea, Request |
| **Making things** | Bug, Feature, Art, Playtest note |
| **Learning** | Assignment, Reading |

Some bring fields of their own, such as an Event's **Location**, a Purchase's **Cost** and **Link**, or a Bill's **Amount**. These are added to the initiative's [metadata](initiatives.md#metadata), or reused if it already has one by that name, and placed on the new type's page.

### Rename, recolor or reorder types

1. On the **Task types** tab, change the name, icon or color in the table, or drag a row by its handle.
2. To choose the type new tasks start as, select the circle in the **Default** column.
3. Select **Save changes**.

### Choose what a new task of a type starts with

A type can fill in a new task's empty fields: an outline for the description, checklist lines, a priority, a repeat. A Bug from the ready-made shelf starts with "What happened / What should have happened / How to make it happen again", a Chore repeats every week and a Bill every month.

1. On the **Task types** tab, select the list button beside the type. A dot on it means the type already starts with something.
2. Fill in the **Description**, the **Checklist** lines (**Add a line** for each), the **Priority** and the repeat.
3. Select **Save**.

When somebody adds a task, these are already filled in, and they change with the type they pick until they change them by hand. Anything they type themselves always wins, and a repeat only starts on a task with a start or due date to count from.

### Copy types from another project

1. On the **Task types** tab, select **Copy from a project**.
2. Pick the **Project**.
3. Tick the types you want.
4. Select **Copy** (it says how many).

Each comes with its icon, color, page and what it starts with. A type whose name this project already has is skipped. A project made from a template brings its types along anyway.

### Lay out a type's page

Select **Edit page** beside the type. It opens the [layout editor](layouts.md) on that type's page, where you can move fields around, require some, or add a new field just for this type. This takes the project's owner, one of the initiative's managers or a community admin, and a tablet or a computer.

### Delete a type

1. On the **Task types** tab, select the bin icon on its row.
2. Under **Move its tasks to**, pick the type they should become.
3. Select **Delete**.

Its page goes with it, and its tasks stay, as the type you picked. The project's last type can't be deleted, because every task needs one.

## Add a field to a project's tasks { #project-properties }

Some things only matter in one project: the sprint a bug landed in, which van the delivery goes on. Nobody planning the spring bake sale needs a "Van" box on their tasks, so it doesn't belong to the whole initiative.

That's a **property**: a field that belongs to the project and turns up on its tasks alone. The fields every project in the initiative shares are its [metadata](initiatives.md#metadata) instead.

1. Open the project and select **Settings**.
2. Select the **Properties** tab.
3. Select **New property**.
4. Type a **Name** and pick a **Type** (text, a number, a date, a person, a choice from a list and so on). A choice needs its options.
5. Select **Save**.

You can also make one while laying out a page: in the [layout editor](layouts.md#put-a-field-on-a-layout), **Add** offers **New property** and asks under **Belongs to** whether it's the project's or the initiative's.

On the **Properties** tab, the arrows reorder them, the pencil edits one, and the bin deletes one. Deleting a property deletes every task's value of it in this project, so it asks first. A task page that shows all properties picks up a new one straight away; a board card or a table column only shows one you add to its layout.

## Start projects from a template { #templates }

Set a project up exactly how you like it, then make it a **template**: a project meant to be copied rather than worked in. Ideal for anything you do more than once, like every new client, every tournament or every school play. Nobody forgets the step at the end, because the step at the end is already there.

To make a project a template, do any one of these:

- Choose **Template** under **Status** at the top of the project.
- Switch on **Template** under **Settings** › **Details**.
- Switch on **Save as template** while making the project.

Templates are listed under **Templates** in the **Show** menu on the **Projects** tab.

To start a new project from one:

1. Select **Add Project**.
2. Pick the template under **Template (optional)**.
3. Give the new project a **Start date** if you want the tasks' dates to follow it.
4. Select **Create project**.

The new project gets the template's tasks, statuses, types, properties and layouts. Its checklists arrive exactly as the template has them, ticks and all. Give it a start date and the task dates move with it: a task due three weeks after the template's start lands three weeks after the new project's.

## Duplicate a project

1. Open the project and select **Settings**.
2. Select the **Advanced** tab.
3. Under **Duplicate**, select **Duplicate**.
4. Pick the **Initiative** it goes into and change the name if you like.
5. Select **Duplicate**.

The copy brings the statuses, types, properties, layouts and every task, with the tasks' tags and links. Their property values come too while the copy stays in the same initiative, and their checklists start unticked. Anyone who can read a template can duplicate it. More on copying in [Tools](tools.md#duplicating).

## Export a project { #exporting-a-project }

Only the project's owner can export it.

1. Open the project and select **Settings**.
2. Select the **Advanced** tab.
3. Under **Export**, pick a format: **Importable file (.json)** for a copy you can bring back in here or on another server, or **PDF document**, **CSV** or **Excel (XLSX)** for a report.

The importable file carries the project's [layouts](layouts.md) too, so it comes back looking the way you left it. Bring it back with **More actions** › **Import from file** on any initiative's **Projects** tab. Plug-ins belong to a community, so they stay behind; wherever the file lands, the plug-ins that initiative has show up on it as they would on any project. A preset that picks out particular people or tags arrives without them.

To export just some of a project's tasks, see [Export the task list](project-views.md#export-the-task-list).

!!! note "People are named by handle"
    An export identifies assignees, event attendees and person fields by **handle** (`foobar#1234`), because a handle is the same in every community and an email address isn't.

## Archive or delete a project

**Archive** a finished project to put it away without losing anything. Choose **Archived** under **Status** at the top of the project, or select **Archive** under **Settings** › **Advanced**. The project and everything in it turns read-only, and it moves to **Archived** in the **Show** menu on the **Projects** tab. **Unarchive** brings it back.

Only the project's owner can delete it:

1. Open the project and select **Settings**.
2. Select the **Advanced** tab.
3. Under **Danger Zone**, select **Delete**.
4. Select **Delete** again to confirm.

It goes to the community's trash, where it can be restored until the retention period runs out.

## Pin, bookmark and order your projects

On the **Projects** tab, each project's card has two buttons:

- **Bookmark** adds it to your **Bookmarks** in the sidebar and on Home. It's yours alone. See [Bookmarks](your-space.md#bookmarks).
- **Pin project** marks it as pinned for everyone in the initiative. That takes the project's owner, one of the initiative's managers or a community admin.

To put projects in your own order, drag them by their handles. It works on the first page of **Active** projects with no filter, search or sort applied, and the order is yours alone.
