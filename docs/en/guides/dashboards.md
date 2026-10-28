---
icon: lucide/chart-line
---

# Dashboards

A **dashboard** is one screen that answers "how are we doing?" — without anybody having to open five things and do sums in their head first.

It's a canvas of tiles — charts, single big numbers, timelines, boards — each reading from your own data. Open tasks by status. Progress against a deadline. What's on this week. A counter's current value.

Whatever the person who keeps asking the question actually needs to see, so that they stop asking.

![An initiative dashboard](../images/tools/dashboard.png)

## Dashboards only display

Nothing on a dashboard can be edited from it. That isn't a compromise we made — it's the entire point.

It means you can leave one running on a screen in the corner of the room, or send it to a board member, or hand a tablet to a volunteer, without the low background hum of anxiety that normally comes with handing somebody a live system.

The worst thing anyone can do to a dashboard is look at it.

## Everyone sees their own version

Each tile shows *you* only what you're already allowed to see.

So two people can open the same dashboard and correctly see different numbers, and neither of them is looking at a bug.

The access rules you set on projects and files follow straight through into the reporting — which means a dashboard is never the accidental side door to something somebody wasn't supposed to see.

## Run dashboard as

There is one case where that's wrong, and it's the case dashboards get built for: the number everybody in the room is supposed to be looking at. A total that's smaller for half the meeting isn't a total, it's an argument.

So under **Settings → Details**, **Run dashboard as** has two choices:

- **Individual** — the default. Everyone sees only what they can open, so numbers can differ from person to person.
- **Initiative** — everyone sees the same numbers, with full read access to the initiative, whatever their own permissions. Use it with care: people will see figures from things they can't open themselves.

**Initiative** is the dashboard's own access, not a person's. It doesn't change when whoever turned it on leaves or changes role, and it only ever reads — nothing on a dashboard can change your data.

Who may turn it on is a role permission, **Run dashboards as Initiative**, under **Initiative settings → Roles**. Managers always can. Changing the tiles of a dashboard that runs as Initiative takes the same permission, since the tiles decide what everybody sees; anyone else who can edit it can switch it back to **Individual** first.

## Building one

From the initiative's **Dashboards** tab: **New Dashboard**. Add tiles, point each at what it should read, arrange them on the canvas. In the list, each dashboard's card is a small copy of it, so you can pick the right one by its shape.

Or skip the building entirely. **Browse the marketplace**, in the list's **More actions** menu — or beside **Create Your First Dashboard** while there are none — has ready-made dashboards you add in a couple of clicks and then adjust. See [Plug-ins & the marketplace](plugins-and-marketplace.md).

Usually faster than starting from a blank canvas, and often better, because somebody else has already spent a year discovering which four numbers actually matter and which nine just look impressive.

!!! tip "Steal a layout, then change it"
    A marketplace dashboard becomes an ordinary dashboard of yours the second you add it. Rename it, rearrange it, delete the tiles you don't like. Nothing phones home and nobody's feelings are hurt.

### Pointing a tile at something

Two steps, and most people never leave the first.

**Build** is clicking. Pick what to read — tasks, files, queue items, notices, events, your community's own people, or **Metadata and property values**, the initiative's and its projects' and collections' own fields wherever they're set — then which columns, what to group them by, and what to narrow it to. The dashboard writes the query for you.

**SQL** is the tab beside it, for the question clicking can't describe. It's real SQL, with the tables and columns offered as you type and the statement checked as you pause. One thing to know before you start: once you've edited the text, **Build** can't read it back. It offers to build a new query instead, which replaces what you wrote, so it never quietly mangles it.

Either way you can reach what a thing is *attached to* without writing a join. Tasks by the person assigned, by their status, by their project — pick the related column and the rest is worked out.

### Narrowing it

The **Filters** say which rows a tile is about. Pick a field, how to compare it, what to compare it against. With more than one, choose whether rows must match **all** of them or **any**, and add a group for the other kind when "high or urgent, and mine" is the actual question.

Archived work and templates are left out to start with. **Archived** and **Templates** above the filters each say **Leave out**, **Include** or **Only** — so "everything we archived this year" is one click away. Deleted things are never counted, on any dashboard, for anyone.

Dates are asked as distances rather than as dates. A tile set to *the next 30 days* still means that next month, which is the whole difference between a dashboard and a screenshot.

### A tile that's about whoever's looking

Wherever a filter wants a person, one of the choices is **Me**.

That doesn't mean you. It means whoever is looking at the tile. Place *My open tasks* once and everybody who opens that dashboard sees theirs — one tile, not one per person, and nobody's name stored inside it.

(On a dashboard that runs as **Initiative**, *Me* is still whoever is looking — the tile counts across the whole initiative, then narrows to them.)

### Grouping by time

Group a date by **day**, **week**, **month**, **quarter** or **year** and a chart labels each point that way — "Mar 2026", "Q1 2026" — in order, oldest first. A heatmap draws months and quarters as a row per year, and weeks and years as a single strip.

### Targets, burn-ups and splits

- **A target.** Give a chart, stat or progress bar a **Target** and a **Target date**. The chart draws it as a line, the progress bar marks it, and each says whether you've reached it, are on track, behind, or missed it, judged from the trend so far.
- **A burn-up.** Show a count or total as **Running count** or **Running total**, and each point adds up everything before it.
- **A split.** Group by a second column (status, say, beside the sprint) and a chart draws one series per value; **Stacked** piles them up. Past twelve series, the smallest fold into Other.
- **Points per sprint.** Read **Metadata and property values**, filter by **Metadata or property**, show **Metadata or property › Name** and the total of **Number**, and group by the name.

In SQL, the same tables are `metadata_values` and `metadata_definitions`, and window functions work: `sum(…) OVER (…)`, `row_number()`, `lag()` and friends.

### Subtasks under their parent

Links live in SQL as `relationships`. Each end is a kind and an id, so a join names both, and a subtask is the `source` of a `part_of` link whose `target` is its parent:

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

Give a Gantt `parent` as its **Group**, and each parent's bar folds up with its subtasks. The `#` and id keep two parents both called "Launch" from sharing a group. `done` goes to **Done**, which is how the Gantt knows what's finished: each parent fills up as its subtasks get done, and anything past its end and not done turns red. Without a **Done** column it counts the work and leaves the bars unfilled, because a date passing says nothing about whether anybody finished. A link only shows to somebody who can see both of the things it joins, and one that's been unlinked isn't there at all.

### Boards

One of the tiles is a **board**: your tasks dealt into columns, and you say what a column stands for. A status. The people on the work, so everyone gets a column and you can see who is carrying what. Priority. Project. Any column the tile's query returns will do.

Each value the tasks actually have gets a column. Tasks with nothing in that column share one more, at the end, named for what they're missing.

Like everything else here it only displays. There's nothing to drag a card onto — moving work between states is still a project's job.

### Widgets from the marketplace

Some marketplace tiles are custom **widgets**. They run in an isolated sandbox and can only hand back something to draw — so a widget that misbehaves shows an error in its own tile while the rest of the page carries on as though nothing happened.

## Where they show up

Dashboards live inside an initiative, next to its projects and files, and share the same way — **Viewer**, **Editor**, **Owner**, or the whole initiative. Everything else every tool has, they have too; see [Tools](tools.md). Since "look at this" is the entire use case, they're often the one thing a group opens right up.

Each dashboard has its own comment thread, which is an excellent place to argue about what a number actually means. Switch it off under **Settings → Details** if you'd rather that argument happened somewhere else.

## Related

- [Counters](counters.md) — numbers a dashboard can read.
- [Plug-ins & the marketplace](plugins-and-marketplace.md) — ready-made dashboards.
- [Sharing projects & files](../sharing/sharing-projects-and-files.md) — access levels in full.
- [Your space](your-space.md#my-tools) — every dashboard that's reached you, from every community.
