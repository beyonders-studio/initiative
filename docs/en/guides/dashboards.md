---
icon: lucide/chart-line
---

# Dashboards

A **dashboard** is one screen that answers "how are we doing?", so nobody has to open five things and do sums in their head first. It's a canvas of **widgets** (charts, big single numbers, timelines and boards), each reading from your own data: open tasks by status, progress against a deadline, what's due this week, the bake sale's running total. Put on it whatever the person who keeps asking needs to see, and they'll stop asking.

**Dashboards only display.** Nothing on a dashboard can change your data, so you can leave one running on the TV in the corner, send it to the board treasurer, or hand a tablet to a volunteer without the low background hum of worry that usually comes with handing somebody a live system. The worst anyone can do to a dashboard is look at it.

**Everyone sees their own numbers.** Each widget shows a person only what they're already allowed to open, so two people can look at the same dashboard, see different totals, and neither of them is looking at a bug. When you want everyone to see the same numbers, see [Show everyone the same numbers](#show-everyone-the-same-numbers).

## Make a dashboard

You need a role in the initiative that can create dashboards (**Create Dashboards**). If there's no button, ask one of the initiative's managers.

1. Open the initiative and select its **Dashboards** tab.
2. Select **New Dashboard**. (On a phone, it's the **+** at the bottom of the screen.)
3. Type a **Name**, and a description if you like.
4. To change who can see it, open **Advanced options**.
5. Select **New Dashboard**.

It opens empty, waiting for its first widget. In the list, each dashboard's card is a small copy of it, so you can pick the right one by its shape.

### Start from a ready-made one

Somebody else has often already spent a year finding out which four numbers actually matter and which nine just look impressive.

1. On the **Dashboards** tab, open **More actions** and select **Browse the marketplace**. (With no dashboards yet, it's beside **Create Your First Dashboard**.)
2. Pick one and add it.

It becomes an ordinary dashboard of yours the moment you add it: rename it, rearrange it, delete the widgets you don't like. When its maker publishes a new version, **Version N available** appears on it; selecting that replaces your canvas with the new one, so take it only if you haven't made changes you want to keep. See [Plug-ins & the marketplace](plugins-and-marketplace.md#adding-a-dashboard).

## Add a widget

You need edit access to the dashboard. A dashboard holds up to 50 widgets.

1. Open the dashboard.
2. Select **Add widget**.
3. Pick a widget from the list. The preview on the right draws it with sample data, and **Data** underneath says what it needs.
4. Set any of its options shown under the preview.
5. Select **Add Chart** (or whichever widget you picked).
6. On the new widget, select **Configure** and [point it at your data](#point-a-widget-at-your-data).

New widgets land at the bottom of the canvas.

| Widget | What it draws |
|---|---|
| **Board** | Tasks dealt into columns: by status, by who's on them, or by one of your own fields. |
| **Chart** | Bars, a line, a filled area, or slices of a whole. |
| **Funnel** | Counts from widest to narrowest, with the drop between each stage. |
| **Gantt** | Scheduled work as bars on a shared timeline, folded into groups you can open. |
| **Heatmap** | Daily activity as a calendar grid, one column per week. |
| **Progress** | How far a value has come against its range. |
| **Stat** | One headline number, with an optional trend against the previous period. |
| **Table** | Plain rows and columns. |

!!! screenshot "A dashboard"
    **Show:** a dashboard with four or five widgets (a **Stat**, a **Chart**, a **Progress** bar and a **Gantt**), each with its title and the small line under it saying where it reads from and how many rows.

    Save as `en/images/dashboards/dashboard.png`, then replace this box with:
    `![A dashboard with a stat, a chart, a progress bar and a Gantt](../images/dashboards/dashboard.png)`

## Point a widget at your data

Most people only ever need the **Build** tab, which is all clicking.

1. On the widget, open its menu (the **⋮**) and select **Configure**.
2. Give it a **Title**, or leave it blank to use the widget's own name.
3. On the **Build** tab, pick what to read under **Show data from**: **Tasks**, **Projects**, **Calendar events**, **Counters**, **Metadata and property values** (the initiative's metadata and its projects' and collections' properties, wherever they're set) and so on, through files, wiki pages, posts, contacts and the community's members.
4. Under **Show**, pick a column, and under **Show as**, how to show it: **Value**, **Count**, **Total**, **Average**, **Lowest** or **Highest**.
5. Select **Add a column** for each column you want after that.
6. Add any [filters](#narrow-a-widget-down).
7. Check the **Preview**, then select **Save**.

You can reach what a thing is attached to without any extra setup: pick "Status › Name" or "Project › Name" as a column, for instance, and the rest is worked out.

Once any column is a count or a total, the widget groups by the other columns, and **Group by** under the columns says so ("One row for each…"). A widget fills what it needs from your columns in order: each thing listed under **Data** in the picker takes the first column of the right kind. Put the columns in that order and it draws the way you meant.

### Narrow a widget down

The **Filters** say which rows a widget is about.

1. In **Configure**, on the **Build** tab, select **Add filter**.
2. Pick a **Field**, a **Condition** and a **Value**.
3. Add more filters the same way. Once there are two, choose whether rows must match **all** or **any** of them.
4. For a mixed question, like "high or urgent, and mine", select **Add an "any of" group** or **Add an "all of" group** and use **Add to group** inside it.
5. Select **Save**.

Archived work and templates are left out to start with. **Archived** and **Templates**, above the filters, each offer **Leave out**, **Include** or **Only**, so "everything we archived this year" is one click away.

A date filter can be **Relative**, counted in **Days from today**, or **On a date**. A widget set to "the next 30 days" still means the next 30 days when you open it next month, which is the whole difference between a dashboard and a screenshot.

### Make a widget about whoever's looking

Wherever a filter wants a person, one of the choices is **Me**, which means whoever is looking at the widget rather than whoever set it up. Put "my open tasks" on a dashboard once and everyone who opens it sees their own, with nobody's name stored inside it.

### Group by time

Beside any date column under **Show**, pick how to round it: **By day**, **By week**, **By month**, **By quarter**, **By year**, or **Exact time**. Beside a count or a total, that's how the widget groups its rows, so "tasks finished **By month**" is one point per month.

### Add a target, a running total or a split

- **A target.** A **Chart**, **Stat** or **Progress** widget can take a **Target** and a **Target date**, under **Display** in **Configure**. It draws the target and says whether you've **Reached** it, are **On track**, are **Behind**, or **Missed** it, judged from the trend so far.
- **A running total** (a burn-up). Show a count or total as **Running count** or **Running total**, with another column shown as **Value** beside it, and each point adds up everything before it.
- **A split.** Add a second text column (status, say, beside the sprint) and a **Chart** draws one series per value, as its **Split by**. Choose **Stacked** to pile them up. Past twelve series, the smallest fold into "Other".
- **Points per sprint.** Read **Metadata and property values**, filter by **Metadata or property**, then show **Metadata or property › Name** and the **Total** of **Number**.

## Write the query yourself

**SQL**, the tab beside **Build**, is for the question clicking can't describe. It's a read-only `SELECT` over your community's data, run as you, so it only ever returns what you can already see. The tables and columns are offered as you type, and the statement is checked whenever you pause.

One thing to know before you start: once you've edited the SQL, **Build** can't read it back. It offers **Build a new query**, which replaces what you wrote, so it never quietly mangles it.

Window functions work (`sum(…) OVER (…)`, `row_number()`, `lag()` and friends), and the metadata and properties are in `metadata_values` and `metadata_definitions`.

??? techspec "Subtasks under their parent, on a Gantt"
    Links live in `relationships`. Each end is a kind and an id, so a join names both, and a subtask is the `source` of a `part_of` link whose `target` is its parent:

    ```sql
    SELECT t.title, t.start_date, t.due_date,
           coalesce(p.title || ' #' || p.id, t.title || ' #' || t.id) AS parent,
           s.category = 'done' AS done
    FROM tasks t
    JOIN task_statuses s ON s.id = t.task_status_id
    LEFT JOIN relationships r ON r.source_id = t.id
      AND r.source_type = 'task' AND r.relationship_type = 'part_of'
    LEFT JOIN tasks p ON p.id = r.target_id AND r.target_type = 'task'
    ```

    On a **Gantt** widget, the columns fill its **Label**, **Start**, **End**, **Group** and **Done** in that order, so each parent's bar folds up with its subtasks. The `#` and id keep two parents both called "Launch" from sharing a group. **Done** is how the Gantt knows what's finished: each parent fills up as its subtasks get done, and anything past its end and not done turns red. Without a done column it leaves the bars unfilled, because a date passing says nothing about whether anybody finished. A link only shows to somebody who can see both things it joins.

## Read a spreadsheet

Somebody already keeps the budget in a spreadsheet, and nobody is going to retype it. A widget can read a spreadsheet in the dashboard's initiative.

1. In **Configure**, on the **Build** tab, choose **Spreadsheet** under **Show data from**.
2. Pick the file.
3. Pick the **Sheet**, or leave it on **First visible sheet**.
4. Type a **Range**, or leave it empty for the whole sheet. `A:D` reads columns A to D down to the last filled row.
5. Choose the columns, and select **Save**.

Every column of the range comes in, named by its header row when the first row is all text, or by its letters (A, B, C) when it isn't. Formulas arrive as what they work out to, so the `=SUM()` at the bottom of a column is a number. A widget reads up to 100,000 cells, and it reads the spreadsheet as last saved, which while somebody is typing in it can be up to about half a minute behind.

In **SQL**, a range is `sheet()` in the `FROM`, and from there it's a table like any other, so it can sit right beside your tasks:

```sql
SELECT b.project, b.budget, count(t.id) AS open_tasks
FROM sheet('Budget 2026', 'Q3!A1:B') AS b
JOIN projects AS p ON p.name = b.project
JOIN tasks AS t ON t.project_id = p.id
WHERE t.completed_at IS NULL
GROUP BY b.project, b.budget
```

| Range | Reads |
|---|---|
| `Q3!A1:D20` | Those cells on the sheet called Q3 |
| `Q3!A:D` | Columns A to D, down to the last filled row |
| `Q3!A5:D` | Columns A to D, from row 5 down |
| `Q3` | The whole sheet |
| `A1:D20` | Those cells on the first visible sheet |

Name the spreadsheet by its name, or by its id if you'd like the widget to survive somebody renaming the file to `Budget 2026 FINAL (2)`. A header with a space in it goes in double quotes, `sum("Q3 total")`, and capitals don't matter.

## Read a plug-in's data

A [plug-in](plugins-and-marketplace.md) your community installed can feed a widget too: the online store's orders, the issue tracker's open bugs, whatever it has to say.

1. In **Configure**, on the **Build** tab, choose **Plug-in data** under **Show data from**.
2. Pick the **Plug-in**, then **What it reads**.
3. Fill in anything it asks for, like a date range.
4. Choose the columns, and select **Save**.

In **SQL** it's `plugin()` in the `FROM`: the plug-in's id, the name of what to read, then its settings by name. A setting that takes several values is a list, such as `tags => ARRAY['bug', 'regression']`, and the SQL box offers each plug-in and its settings as you type.

```sql
SELECT o.status, count(*) AS orders, sum(o.total) AS revenue
FROM plugin('acme.shop', 'orders', range => '30d') AS o
GROUP BY o.status
```

Whose account the plug-in answers with follows [Run dashboard as](#show-everyone-the-same-numbers). On **Individual**, it's your own connection to the plug-in when you've made one and the plug-in can use it, and the community's otherwise. On **Initiative**, it's always the community's, so everybody sees the same numbers. A plug-in's answer is reused for as long as the plug-in says it stays fresh, five minutes at most.

## Use the Board widget

A **Board** deals tasks into columns, and you say what a column stands for: a status, the people on the work (so you can see who's carrying what), priority, project, or any text column the widget reads. Each value the tasks actually have gets a column, and tasks with nothing in that column share one more, named for what they're missing.

Its options set the **Card order**, what **Cards show**, whether to **Highlight** anything overdue, and the **Column order**. Like everything else here it only displays, so there's nothing to drag a card onto; moving work along is a project's job.

## Move, resize or remove widgets

- **Move** a widget by dragging its header.
- **Resize** one by dragging its corner.
- **Remove** one with its **⋮** menu and **Remove**. It goes at once, with no second question, so be sure.

The canvas saves as you go. On a phone the widgets stack into one column and stay put, so arrange them on a bigger screen.

## Look under a widget

- **Show as a table** (the icon that appears when you point at a widget) swaps a chart for the rows behind it, and **Show as a chart** swaps it back. Anyone who can see the dashboard can do this.
- The small line under a widget's title ("SQL query · 42 rows") opens **Where this comes from**: what it reads, what it's showing and how. **Refresh** fetches it again.
- A widget reads up to 5,000 rows. When more match, it shows the first 5,000 and a warning says so.

A widget pointed at something you can't open says **You can't see this widget's data**, and one nobody has set up yet says **Choose what this shows**.

## Show everyone the same numbers

Seeing only what you can open is right almost everywhere, except for the number everybody in the meeting is supposed to be looking at. A total that's smaller for half the room just starts an argument.

1. Open the dashboard and select **Settings**.
2. On the **Details** tab, find **Run dashboard as**.
3. Choose **Initiative**.

| Choice | What people see |
|---|---|
| **Individual** | Only what each person can open, so numbers can differ from person to person. New dashboards start here. |
| **Initiative** | The same numbers for everyone, read with full access to the initiative, whatever their own access. People will see figures from things they can't open themselves, so use it with care. |

A dashboard running as **Initiative** says **Same numbers for everyone** at the top. It only ever reads, and it keeps working when whoever switched it on leaves or changes role, because it's the dashboard's setting rather than that person's. **Me** in a filter still means whoever is looking: the widget counts across the whole initiative, then narrows to them.

Choosing **Initiative** takes the role permission **Run dashboards as Initiative**, under the initiative's roles; managers and community admins always have it. So does changing anything about the widgets on such a dashboard, moving and resizing included, since the widgets decide what everybody sees. Anyone else who can edit it can switch it back to **Individual** first.

## Settings, sharing and comments

A dashboard's **Settings** has **Details** (name and description, **Run dashboard as**, **Tags**, **Metadata** and **Comments**), **Access** and **Advanced**. It shares, archives, exports, duplicates and goes to the trash like every other tool; see [Tools](tools.md). Since "look at this" is the whole point, it's often the one thing a group opens right up.

Each dashboard has its own comment thread, which is an excellent place to argue about what a number actually means. Switch it off under **Settings** › **Details** if you'd rather that argument happened somewhere else.
