---
icon: lucide/layout-template
---

# Layouts

A **layout** decides how a tool shows what it holds: which columns a table has, what a card on a board says, where everything sits when you open one thing. Change it once and everybody who opens that tool sees the change.

It changes how things are drawn, never what anybody can see. Filters and sorting stay each person's own.

You can ignore this page entirely. Every layout ships ready to use, and plenty of projects finish without anyone touching one.

## What has one

| Tool | Its layouts |
|---|---|
| [Projects](projects-and-tasks.md#layouts) | **Table**, **Board**, **Gantt**, **Calendar** (each shown or hidden; all four to start with), and a page for each [task type](projects-and-tasks.md#task-types), per project. |
| [Queues](queues.md) | **Queue item detail**, per queue. |
| [Counters](counters.md) | **Counter detail**, per counter group. |
| [Collections](files.md#collections) | **Grid**, **Table**, **Masonry**, **Timeline** (each shown or hidden), per collection. |
| [Calendar](calendar.md) | **Event detail** and the calendar's presets, once for the whole initiative. |
| [Posts](posts.md) | **Notice detail**, once for the whole initiative. |

A detail layout is also how the add dialog is laid out, for tasks, events, queue items and counters. The form you fill in looks like the thing you get.

A project's layouts go wherever the project goes: into a [duplicate](tools.md#duplicating), into an [export](projects-and-tasks.md#exporting-a-project), and out of the marketplace, where a ready-made project arrives laid out the way whoever made it set it up.

## Who can change them

- **A collection:** anyone who can change it.
- **A project, queue, counter group:** whoever owns it, anyone with full access in the initiative, a manager who can edit it, and community admins.
- **The calendar and posts:** the initiative's managers and community admins.

## The editor

Open it from **Settings → Layouts → Edit layouts** on the tool. **Initiative settings → Layouts** lists every layout in the initiative, when each last changed, with the same button beside each.

It needs a tablet or a computer. On a phone the button isn't offered, because a screen that size is no place to rearrange anything.

- **Across the top:** which layout you're editing, a **Desktop**, **Tablet** or **Phone** preview, undo, redo, and **Save**.
- **Outline**, on the left: everything in the layout. Drag to reorder; **Add** puts more in.
- **Preview**, in the middle: the layout drawn with real items.
- **Settings**, on the right: whatever you've selected.

Nothing changes for anyone until you save, and leaving with unsaved changes asks first. **Use the shipped layout** puts one back exactly as it came.

### What goes in

- **Fields.** The built-ins, a project's or a collection's properties, and the initiative's [metadata](initiatives.md#metadata), each under its own heading, or **All metadata** (**All properties and metadata** on a project's tasks) for every value a thing has. Pick a type under **New property** (**New metadata** where there's no project or collection) to make one without leaving the editor; in a project or a collection, it asks whose it is.
- **Plug-in parts**, from plug-ins installed in your community, on a card or a detail.
- **Row**, which puts what it holds side by side. A detail also takes an **Accordion** (a titled section that opens and closes, and can **Start closed**) and a **Box** (a border round what it holds).

A table takes fields and nothing else, since a column is a column.

### Properties

Click the layout's name at the top of the outline and, in a project or a collection, its properties are listed on the right, each saying which layouts show it. Reorder, edit or delete them there, or make a **New property**; a project's are also in **Settings → Properties**. Deleting one takes every value of it with it, so it asks first. A page that shows all properties picks up a new one straight away; cards and tables show only what you add.

The initiative's metadata is edited in [its settings](initiatives.md#metadata). Select a field that shows some and its settings link there.

A table or board layout also says what people may **group by**, what it **starts grouped by**, and which groups to leave out, such as finished sprints. A date groups by day, week, month, quarter or year; pick which beside it. A board's **Column limits** cap how many open tasks a status column holds; once one is full, nobody adds or moves a task into it until one leaves.

A detail layout has three regions: **Header** across the top, **Main** the wide column, **Side** the narrow one beside it. On a phone the regions stack into one column, and the **Phone** preview shows in what order.

Taking a part out hides it. It doesn't delete anything: the values are all still there, and **Add** puts the part back. The title is the one thing every layout keeps.

**Opens first**, on a project's lists, picks the one the project opens on for anybody who hasn't picked their own.

## Required fields

Some things are no use half filled in. A bug report with no steps. A booking with no room. A photo in the shop catalogue with no price, which is how the good teapot went for nothing at the last fete.

So a page can say a field is **required**: select it in the editor and switch on **Required**. That works on a task type's page, the calendar's event page, the posts page and a collection's file page.

- **What can be required:** anything somebody fills in. A description, a checklist, people, tags, dates, how it repeats, a property, a collection's own property. A task's start and due dates count as one, and either date fills them.
- **What can't:** the title, because it always is, and shows as required and locked. Also anything that's never empty (a task's type, status and priority), anything nobody fills in (who made it, when), a checkbox, and a plug-in's fields, which the plug-in fills.
- **What it does:** the add dialog puts required fields up top, never under **More options**, and waits until they're filled. Once filled, nobody can empty one. A required checklist needs one item. One will do.
- **What it leaves alone:** everything that already exists. A task made last Tuesday without a description keeps going without one, and its page marks the gap so the next person to open it can fill it in. Imports, automations, plug-ins and the next copy of a repeating task go through too, and get the same mark.
- **What counts as arriving:** a task changing type, or moving to another project, meets the new page's requirements as if it were new. Anything its new page wants and it hasn't got, Initiative asks for on the spot, in a small box listing only those, and the change goes through with them. Values that came along from the old project count.

Hiding a field lifts the requirement with it. Nobody can fill in what they can't see.

## Presets

A list can offer **presets**: named filters, plus a sort on a table, that anyone can pick from **Filters** as a starting point. Picking one makes those filters that person's own, to narrow further if they like. The preset itself stays as it was.

A project's lists start with **Incomplete**, **Unassigned** and **Mine**. The calendar starts with none. Add, rename, reorder or remove them in the editor under **Presets**, up to 20 per list. Picking one puts it in the page's address, so sharing the link shares the preset.
