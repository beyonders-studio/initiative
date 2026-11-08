"""Dashboards: read-only canvases, each widget one statement."""

from __future__ import annotations

from sqlmodel import select

from app.core.tools import Tool
from app.models.tenant._mixins import ActorKind
from app.models.tenant.counter import Counter
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.services.tenant.dashboard_definition import normalize_dashboard_definition
from seed.common import Community, share


def widget(
    widget_id: str,
    widget_type: str,
    sql: str,
    grid: tuple[int, int, int, int],
    *,
    title: str | None = None,
    options: dict | None = None,
    counter_group: str | None = None,
    counter: tuple[str, str] | None = None,
    project: str | None = None,
) -> dict:
    """One widget in a dashboard definition; ``grid`` is ``(x, y, w, h)``.

    ``sql`` is the statement the widget draws — the whole of what a binding
    says. One that reads a counter or a project cannot be written out here: a
    seed knows those by name and only the inserted row knows the id, so it
    writes ``{counter_id}``/``{counter_group_id}``/``{project_id}``, names the
    row alongside (``counter`` is ``(group, counter)``), and ``seed`` fills
    them in once the rows exist. There is deliberately no initiative in any of
    these: a dashboard reads within the initiative it lives on.
    """
    x, y, w, h = grid
    spec: dict = {
        "id": widget_id,
        "type": widget_type,
        "grid": {"x": x, "y": y, "w": w, "h": h},
        "binding": {"source": "query", "sql": sql},
    }
    refs = {"counter_group": counter_group, "counter": counter, "project": project}
    if any(refs.values()):
        spec["_refs"] = refs
    if title:
        spec["title"] = title
    if options:
        spec["options"] = options
    return spec


#: Each dashboard, shared the way ``share`` reads it.
DASHBOARDS: dict[str, list[dict]] = {
    "primary": [
        {
            "name": "Campaign Overview",
            "initiative": "strahd",
            "description": "Where the party stands, at a glance.",
            "created_by": "Dungeon Master",
            "general": ResourceAccessLevel.read,
            "widgets": [
                widget(
                    "w1",
                    "stat",
                    "SELECT count AS hit_points FROM counters WHERE id = {counter_id}",
                    (0, 0, 3, 2),
                    title="Thorn's hit points",
                    counter=("Party Vitals (Strahd)", "Thorn HP"),
                ),
                widget(
                    "w2",
                    "stat",
                    "SELECT count(*) AS open FROM tasks WHERE completed_at IS NULL",
                    (3, 0, 3, 2),
                    title="Open threads",
                ),
                widget(
                    "w3",
                    "chart",
                    "SELECT s.category AS stage, count(*) AS tasks FROM tasks t "
                    "JOIN task_statuses s ON t.task_status_id = s.id "
                    "GROUP BY s.category",
                    (6, 0, 6, 4),
                    title="Work by status",
                    options={"mark": "bar"},
                ),
                widget(
                    "w4",
                    "progress",
                    "SELECT count(completed_at) AS finished, count(*) AS total FROM tasks",
                    (0, 2, 6, 2),
                    title="Arc completion",
                ),
                widget(
                    "w5",
                    "gantt",
                    "SELECT title, start_date, due_date FROM tasks "
                    "WHERE start_date IS NOT NULL ORDER BY start_date",
                    (0, 4, 12, 6),
                    title="Session schedule",
                    options={"scale": "week"},
                ),
            ],
        },
        {
            "name": "Barovia Prep (private)",
            "initiative": "strahd",
            "description": "The DM's own board — nobody else is on it.",
            "created_by": "Dungeon Master",
            "widgets": [
                widget(
                    "w1",
                    "table",
                    "SELECT title, priority, due_date FROM tasks "
                    "WHERE project_id = {project_id} AND completed_at IS NULL "
                    "ORDER BY due_date",
                    (0, 0, 12, 5),
                    title="Everything still open",
                    project="Barovia Arc",
                ),
                widget(
                    "w2",
                    "heatmap",
                    "SELECT date_trunc('day', completed_at) AS day, count(*) AS finished "
                    "FROM tasks WHERE completed_at IS NOT NULL "
                    "GROUP BY date_trunc('day', completed_at) "
                    "ORDER BY date_trunc('day', completed_at)",
                    (0, 5, 8, 3),
                    title="Prep activity",
                ),
            ],
        },
        {
            "name": "Quest Board",
            "initiative": "lmop",
            "description": "Phandalin at a glance.",
            "created_by": "Dungeon Master",
            "roles": [("lmop", ResourceAccessLevel.write)],
            "widgets": [
                widget(
                    "w1",
                    "stat",
                    "SELECT count(*) AS open FROM tasks WHERE completed_at IS NULL",
                    (0, 0, 3, 2),
                    title="Quests in flight",
                ),
                widget(
                    "w2",
                    "funnel",
                    "SELECT s.category AS stage, count(*) AS tasks FROM tasks t "
                    "JOIN task_statuses s ON t.task_status_id = s.id "
                    "GROUP BY s.category",
                    (3, 0, 6, 5),
                    title="Quest pipeline",
                ),
                widget(
                    "w3",
                    "table",
                    "SELECT p.name AS project, count(*) - count(t.completed_at) AS open, count(*) AS total "
                    "FROM projects p JOIN tasks t ON t.project_id = p.id "
                    "GROUP BY p.name ORDER BY p.name",
                    (0, 5, 12, 5),
                    title="Adventure arcs",
                ),
            ],
        },
    ],
    "starforge": [
        {
            "name": "Mission Status",
            "initiative": "starfall",
            "description": "Ship, crew, and schedule on one screen.",
            "created_by": "Elara Moonwhisper",
            "general": ResourceAccessLevel.read,
            "widgets": [
                widget(
                    "w1",
                    "progress",
                    "SELECT count AS reading, max AS capacity FROM counters "
                    "WHERE id = {counter_id}",
                    (0, 0, 4, 2),
                    title="Hull integrity",
                    counter=("Fleet Status", "Hull Integrity"),
                ),
                widget(
                    "w2",
                    "stat",
                    "SELECT count AS days FROM counters WHERE id = {counter_id}",
                    (4, 0, 3, 2),
                    title="Days to Kepler-442b",
                    counter=("Fleet Status", "Days to Kepler-442b"),
                ),
                widget(
                    "w3",
                    "chart",
                    "SELECT name, count AS reading FROM counters "
                    "WHERE counter_group_id = {counter_group_id} ORDER BY name",
                    (7, 0, 5, 4),
                    title="Fleet readings",
                    counter_group="Fleet Status",
                ),
                widget(
                    "w4",
                    "chart",
                    "SELECT s.category AS stage, count(*) AS tasks FROM tasks t "
                    "JOIN task_statuses s ON t.task_status_id = s.id "
                    "GROUP BY s.category",
                    (0, 2, 7, 4),
                    title="Work by status",
                    options={"mark": "pie"},
                ),
                widget(
                    "w5",
                    "table",
                    "SELECT title, priority, due_date FROM tasks "
                    "WHERE completed_at IS NULL ORDER BY due_date",
                    (0, 6, 12, 5),
                    title="Open work",
                ),
            ],
        }
    ],
    "tides": [
        {
            "name": "The Crimson Maiden",
            "initiative": "crimson",
            "description": "Ship's condition and the crew's work.",
            "created_by": "Vex Shadowstep",
            "general": ResourceAccessLevel.write,
            "widgets": [
                widget(
                    "w1",
                    "progress",
                    "SELECT count AS reading, max AS capacity FROM counters "
                    "WHERE id = {counter_id}",
                    (0, 0, 4, 2),
                    title="Hull",
                    counter=("The Crimson Maiden", "Hull HP"),
                ),
                widget(
                    "w2",
                    "progress",
                    "SELECT count AS reading, max AS capacity FROM counters "
                    "WHERE id = {counter_id}",
                    (4, 0, 4, 2),
                    title="Crew morale",
                    counter=("The Crimson Maiden", "Crew Morale"),
                ),
                widget(
                    "w3",
                    "stat",
                    "SELECT count AS days FROM counters WHERE id = {counter_id}",
                    (8, 0, 4, 2),
                    title="Rations left",
                    counter=("The Crimson Maiden", "Rations (days)"),
                ),
                widget(
                    "w4",
                    "chart",
                    "SELECT date_trunc('day', completed_at) AS day, count(*) AS finished "
                    "FROM tasks WHERE completed_at IS NOT NULL "
                    "GROUP BY date_trunc('day', completed_at) "
                    "ORDER BY date_trunc('day', completed_at)",
                    (0, 2, 6, 4),
                    title="Voyage work",
                    options={"mark": "line"},
                ),
                widget(
                    "w5",
                    "progress",
                    "SELECT p.name AS project, count(t.completed_at) AS finished, count(*) AS total "
                    "FROM projects p JOIN tasks t ON t.project_id = p.id "
                    "GROUP BY p.name ORDER BY p.name",
                    (6, 2, 6, 4),
                    title="Voyage legs",
                    options={"breakdown": "each"},
                ),
            ],
        }
    ],
}


async def _row_ids(c: Community, refs: dict) -> dict[str, int | None]:
    """The ids a widget's statement names, from the rows it names."""
    found: dict[str, int | None] = {}
    if refs["project"]:
        found["project_id"] = c.projects[refs["project"]].id
    group_name = refs["counter_group"] or (refs["counter"] or (None,))[0]
    if group_name:
        found["counter_group_id"] = c.counter_groups[group_name].id
    if refs["counter"]:
        counter = (
            await c.session.exec(
                select(Counter).where(
                    Counter.counter_group_id == found["counter_group_id"],
                    Counter.name == refs["counter"][1],
                )
            )
        ).one()
        found["counter_id"] = counter.id
    return found


async def seed(c: Community) -> None:
    """Every definition goes through the real normalizer before it is stored,
    so a seed that drifts from the widget vocabulary — or writes a statement
    the query surface refuses — fails here rather than rendering as an error
    tile."""
    for d in DASHBOARDS.get(c.key, []):
        creator = c.users[d["created_by"]]
        widgets = []
        for raw in d["widgets"]:
            spec = dict(raw)
            refs = spec.pop("_refs", None)
            if refs:
                sql = spec["binding"]["sql"].format(**await _row_ids(c, refs))
                spec["binding"] = {**spec["binding"], "sql": sql}
            widgets.append(spec)
        dashboard = Dashboard(
            initiative_id=c.initiatives[d["initiative"]].id,
            name=d["name"],
            description=d.get("description"),
            definition=normalize_dashboard_definition(
                {
                    "schema_version": 1,
                    "kind": "dashboard",
                    "layout": {"columns": 12},
                    "widgets": widgets,
                }
            ),
            created_by=creator.id,
            created_by_kind=ActorKind.member,
        )
        c.session.add(dashboard)
        await c.session.flush()
        c.ids["dashboards"].append(dashboard.id)
        share(
            c,
            Tool.dashboard,
            dashboard,
            creator,
            roles=d.get("roles", ()),
            general=d.get("general"),
        )
        await c.session.flush()
