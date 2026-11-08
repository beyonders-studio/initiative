---
icon: lucide/layout-template
---

# Layouts

A **layout** decides how a tool shows what it holds: which columns a table has, what a card on a board says, where everything sits when you open one task. Change it once and everybody who opens that tool sees the change.

It changes how things are drawn, never what anybody is allowed to see, and filters and sorting stay each person's own. You can ignore this page entirely. Every layout ships ready to use, and plenty of projects finish without anyone ever touching one.

## What has a layout

| Tool | Its layouts |
|---|---|
| [Projects](projects-and-tasks.md) | **Table**, **Board**, **Gantt** and **Calendar**, plus a page for each [task type](project-setup.md#task-types). One set per project. |
| [Counters](counters.md) | **Counter detail**, one per counter group. |
| [Collections](files.md#put-files-in-a-collection) | **Grid**, **Table**, **Masonry** and **Timeline**, plus the **File page**. One set per collection. |
| [Calendar](calendar.md) | **Event detail** and the calendar's presets, once for the whole initiative. |
| [Posts](posts.md) | **Notice detail**, once for the whole initiative. |

A page layout (a task's, an event's, a counter's) also lays out the dialog for adding one, so the form you fill in looks like the thing you get.

A project's layouts go wherever the project goes: into a [duplicate](tools.md#duplicating), into an [export](project-setup.md#exporting-a-project), and out of the marketplace, where a ready-made project arrives laid out the way its maker set it up.

## Who can change them

- **A project or a counter group:** its owner, the initiative's managers and community admins, as long as they can edit it.
- **A collection:** anyone who can change the collection.
- **The calendar and posts:** the initiative's managers and community admins.

Everybody else sees the result. Changing a layout needs a tablet or a computer, because a phone screen is no place to rearrange anything.

## Open the layout editor

For a project or a counter group:

1. Open it and select **Settings**.
2. Select the **Layouts** tab.
3. Select **Edit layouts**, or select one layout's name to open the editor on that one.

For a collection, open **Layouts** from the collection's menu. For the calendar and posts, open the initiative's settings and select **Layouts**: that tab lists every layout in the initiative, when each last changed, and the way into each one's editor.

The editor fills the screen:

- **Across the top:** the layout you're editing (pick another here), a **Desktop**, **Tablet** or **Phone** preview, undo, redo, **Discard** and **Save**.
- **On the left:** the outline, listing everything in the layout. **Add** at the bottom puts more in.
- **In the middle:** the preview, drawn with real items.
- **On the right:** settings for whatever you've selected. Select the layout's name at the top of the outline for the layout's own.

Nothing changes for anyone until you select **Save**. **Discard** throws away everything since the last save, ++ctrl+z++ undoes one step (++ctrl+shift+z++ redoes it), and closing the editor with unsaved changes asks before it lets you go.

## Change what a card or a table shows

1. Open the layout editor on the **Board** or the **Table**.
2. To add something, select **Add** and pick it.
3. To move something, drag it by its handle in the outline.
4. To take something off, select it and choose **Hide**.
5. Select **Save**.

Hiding a field doesn't delete anything. Every value is still there, and **Add** puts the field back. The title is the one thing every layout keeps.

A table holds fields and nothing else, since a column is a column. A card can also hold a **Row**, which puts what it holds side by side, and the parts plug-ins installed in your community offer.

## Put a field on a layout

**Add** lists everything a layout can show, grouped:

- **Layout**: the blocks that group other parts, such as a **Row**.
- **Built-in**: the dates, assignees, checklist, priority and the rest.
- **This project's properties** (or **This collection's properties**) and **Initiative metadata**, each field by name.
- **Panels**: bigger pieces, like **All metadata** (**All properties and metadata** on a task), which shows every value a thing has in one go.
- The fields and parts of installed plug-ins, under each plug-in's name.

Type in the search box at the top to find one. To make a brand-new field without leaving the editor:

1. Select **Add**.
2. Under **New property** (or **New metadata**), pick a type.
3. Type its **Name**.
4. In a project or a collection, choose under **Belongs to** whether it's this project's or collection's own, or **The initiative's metadata**.
5. Select **Create**.

The new field goes straight onto the layout. A page that shows all properties picks it up everywhere at once; cards and tables show only what you add to them.

### Manage properties from the editor

Select the layout's name at the top of the outline. In a project or a collection, its properties are listed on the right, each saying which layouts show it. Reorder, edit or delete them there, or make a **New property**. Deleting one deletes every value of it, so it asks first. The initiative's metadata is changed in [its settings](initiatives.md#metadata); select a metadata field and its settings link there.

## Lay out a page

A task's, an event's, a counter's, a notice's and a file's page each have a layout, and a project has one for each task type.

A page has three regions: **Header** across the top, **Main** the wide column and **Side** the narrow one beside it. On a phone the regions stack into one column; the **Phone** preview shows the order.

1. Open the layout editor and pick the page from the menu at the top.
2. Drag parts between regions in the outline, or select **Add** for more.
3. To group parts, add a **Row** (side by side), an **Accordion** (a titled section that opens and closes) or a **Box** (a border around what it holds).
4. Select a group to set how it's arranged on the right: **Arrange**, **Spacing**, and for an accordion its **Title** and whether to **Start closed**.
5. Select **Save**.

A part of the page you've taken off, such as **Comments** or **Relations** (what the thing is linked to), waits under **Panels** in **Add** until you put it back.

## Make a field required { #required-fields }

Some things are no use half filled in: a bug report with no steps, a booking with no room, an item in the silent auction with no starting bid (which is how the good casserole dish went for nothing last spring). So a page can make a field **required**.

1. Open the layout editor on a task type's page, the calendar's event page, the posts page or a collection's file page.
2. In the outline, select the asterisk beside the field.
3. Select **Save**.

Select the asterisk again to make it optional.

- **What can be required:** anything somebody fills in, such as a description, a checklist, people, tags, dates, the repeat, or a property. A task's start and due dates count as one, and either date satisfies it. On a file page, only the collection's own properties can be.
- **What can't:** the title, because it always is (its asterisk stays pressed and won't budge). Also anything that's never empty, like a task's type, status and priority; anything nobody fills in, like who made it; a checkbox; and a plug-in's fields, which the plug-in fills. None of those has an asterisk.
- **What it does:** the add dialog puts required fields up top, never under **More options**, and waits until they're filled. Once filled, nobody can empty one. A required checklist needs one item, and one will do.
- **What it leaves alone:** everything that already exists. A task made last Tuesday without a description keeps going without one, and its page marks the gap so the next person to open it can fill it in. Imports, plug-ins and the next copy of a repeating task go through too, with the same mark.
- **When a task changes type or moves project:** it meets the new page's requirements as if it were new. Initiative asks for anything missing in a small box listing only those fields, and the change goes through with them.

Hiding a field lifts its requirement too. Nobody can fill in what they can't see.

## Offer a preset { #presets }

A **preset** is a named set of filters, and on a table a sort, that anyone can pick from **Filters** as a starting point. A project's lists start with **Incomplete**, **Unassigned** and **Mine**; the calendar starts with none.

1. Open the layout editor on the list.
2. Select the layout's name at the top of the outline, and find **Presets** on the right.
3. Select **Add preset**.
4. Type a **Name**, set the filters, and on a table pick **Sort by** (and **Descending** if you like).
5. Select **Done**.
6. Select **Save**.

The pencil beside a preset edits it, the arrows reorder them, and the bin removes one. A list offers up to 20. Picking a preset makes its filters that person's own, and puts it in the page's address so the link shares it.

## Choose what people can group by

A table, board or Gantt says what people may group it by, and what it starts grouped by.

1. Open the layout editor on the list.
2. Select the layout's name at the top of the outline, and find **Group by** on the right.
3. Untick anything you don't want offered, and use the arrows to put the rest in order.
4. For a date, pick how it's grouped: **By day**, **By week**, **By month**, **By quarter** or **By year**.
5. Under **Starts grouped by**, pick what the list opens grouped by, or **Not grouped**.
6. Select **Save**.

To leave one group out (finished sprints, say), pick its grouping above the preview, then select the group under **Groups shown:**. Select it again to bring it back.

## Cap a board column { #cap-a-board-column }

A **column limit** caps how many open tasks a status column on a project's board holds.

1. Open the layout editor on the **Board**.
2. Select the layout's name at the top of the outline, and find **Column limits** on the right.
3. Type a number beside each column you want to cap. Leave one empty for no limit.
4. Select **Save**.

Once a column is full, nobody can add a task to it or move one in until one leaves. What's already there stays. Repeating tasks, imports and copies aren't held to it.

## Show or hide a view { #show-or-hide-a-view }

A project shows all four views to start with. Switch off the ones nobody uses and they leave the view menu for everyone; at least one always stays.

1. Open the project and select **Settings**.
2. Select the **Layouts** tab.
3. Switch each view on or off.

To choose the view the project opens on for anybody who hasn't picked their own, select the star beside it. You can do both in the editor too, with **Shown in the layout menu** and **Opens first**. A collection's views work the same way, and a new collection shows its **Grid** and **Table**.

## Go back to the shipped layout

1. Open the layout editor on the layout.
2. Select **Use the shipped layout**.
3. Select **Save**.

It goes back exactly as it came. In the **Layouts** list, a layout nobody has changed shows a dash where the date of its last change would be.
