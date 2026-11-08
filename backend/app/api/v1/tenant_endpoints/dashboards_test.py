"""Tests for the dashboard endpoints — CRUD, sharing, and the authorization
gates (feature gate, role create gate, DAC levels, initiative isolation).

The dashboard-specific concern beyond the usual tool contract: sharing a
dashboard shares the canvas, never the data it displays, and no endpoint
accepts anything that would let a definition write.
"""

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.guild import CommunityRole
from app.testing import create_dashboard, create_project, strip_non_owner_grants


def _stat_definition() -> dict:
    return {
        "widgets": [
            {
                "id": "w1",
                "type": "stat",
                "title": "Open bugs",
                "binding": {
                    "source": "query",
                    "sql": "SELECT count(*) AS n FROM tasks",
                },
            }
        ]
    }


async def _dashboards_enabled(session: AsyncSession, initiative) -> None:
    initiative.dashboards_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


async def test_canvas_retains_sql_calendar_date_kind(client, session, acting_user):
    actor = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _dashboards_enabled(session, actor.initiative)
    await create_project(session, actor.initiative, actor.user)
    dashboard = await create_dashboard(
        session,
        actor.initiative,
        actor.user,
        definition={
            "widgets": [
                {
                    "id": "dates",
                    "type": "table",
                    "binding": {
                        "source": "query",
                        "sql": (
                            "SELECT date '2026-08-03' AS day,"
                            " timestamptz '2026-08-03T00:00:00Z' AS at"
                            " FROM projects LIMIT 1"
                        ),
                    },
                }
            ]
        },
    )
    response = await client.get(
        actor.g(f"/dashboards/{dashboard.id}/data"), headers=actor.headers
    )
    assert response.status_code == 200, response.text
    result = response.json()["widgets"]["dates"]["result"]
    assert [column["date_only"] for column in result["columns"]] == [True, False]
    assert result["rows"] == [[1785715200000, 1785715200000]]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def test_create_dashboard(client: AsyncClient, acting_user, session):
    """Creating a dashboard stores a normalized definition and seeds the
    creator's owner grant plus the default all-members read grant."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)

    response = await client.post(
        a.g("/dashboards/"),
        headers=a.headers,
        json={
            "name": "Delivery",
            "description": "Release health",
            "initiative_id": a.initiative.id,
            "definition": _stat_definition(),
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Delivery"
    # Canonicalized on the way in.
    assert body["definition"]["schema_version"] == 1
    assert body["definition"]["kind"] == "dashboard"
    assert body["definition"]["widgets"][0]["type"] == "stat"
    assert body["can"]["delete"] is True
    assert body["listing_uid"] is None


async def test_create_rejects_unknown_widget_type(
    client: AsyncClient, acting_user, session
):
    """A definition naming a widget we don't render is refused, not stored."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)

    response = await client.post(
        a.g("/dashboards/"),
        headers=a.headers,
        json={
            "name": "Bad",
            "initiative_id": a.initiative.id,
            "definition": {
                "widgets": [
                    {
                        "type": "iframe",
                        "binding": {
                            "source": "query",
                            "sql": "SELECT count(*) AS n FROM tasks",
                        },
                    }
                ]
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "DASHBOARD_WIDGET_TYPE_UNKNOWN"


async def test_create_requires_feature_enabled(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    # The factory switches every tool on, so a test about one being OFF
    # turns it off.
    a.initiative.dashboards_enabled = False
    session.add(a.initiative)
    await session.commit()

    response = await client.post(
        a.g("/dashboards/"),
        headers=a.headers,
        json={"name": "Nope", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 403
    assert response.json() == Tool.dashboard.disabled().body


async def test_list_and_read_dashboard(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)
    dashboard = await create_dashboard(session, a.initiative, a.user, name="Ops")

    listing = await client.get(a.g("/dashboards/"), headers=a.headers)
    assert listing.status_code == 200
    assert [d["name"] for d in listing.json()["items"]] == ["Ops"]
    # The list omits the canvas body — only the detail read carries it.
    assert "definition" not in listing.json()["items"][0]
    assert listing.json()["items"][0]["preview"] is None

    # Asked for previews, the list carries each canvas for its card.
    previewed = await client.get(
        a.g("/dashboards/"), headers=a.headers, params={"include_preview": True}
    )
    preview = previewed.json()["items"][0]["preview"]
    assert preview["definition"]["widgets"][0]["type"] == "stat"
    # Its widgets draw from sample data, so the list answers none of them.
    assert set(preview) == {"definition", "config"}

    detail = await client.get(a.g(f"/dashboards/{dashboard.id}"), headers=a.headers)
    assert detail.status_code == 200
    assert detail.json()["definition"]["widgets"][0]["type"] == "stat"


async def test_update_definition_revalidates(client: AsyncClient, acting_user, session):
    """Re-authoring the canvas is the one write a dashboard has, and it goes
    through the same validator as create."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)
    dashboard = await create_dashboard(session, a.initiative, a.user)

    ok = await client.patch(
        a.g(f"/dashboards/{dashboard.id}"),
        headers=a.headers,
        json={
            "definition": {
                "widgets": [
                    {
                        "id": "chart1",
                        "type": "line_chart",
                        "binding": {
                            "source": "query",
                            "sql": "SELECT count(*) AS n FROM tasks",
                        },
                    }
                ]
            }
        },
    )
    assert ok.status_code == 200, ok.text
    widget = ok.json()["definition"]["widgets"][0]
    # Presets are stored resolved: the renderer only ever sees a primitive.
    assert widget["type"] == "chart"
    assert widget["options"]["mark"] == "line"

    bad = await client.patch(
        a.g(f"/dashboards/{dashboard.id}"),
        headers=a.headers,
        json={
            "definition": {
                "widgets": [
                    {
                        "type": "stat",
                        "binding": {
                            "source": "query",
                            "sql": "SELECT secret FROM pg_shadow",
                        },
                    }
                ]
            }
        },
    )
    assert bad.status_code == 422
    assert bad.json()["detail"] == "QUERY_UNKNOWN_RELATION"


async def test_config_for_removed_widget_is_dropped(
    client: AsyncClient, acting_user, session
):
    """Config can't outlive the widget it configures."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)
    dashboard = await create_dashboard(session, a.initiative, a.user)

    response = await client.patch(
        a.g(f"/dashboards/{dashboard.id}"),
        headers=a.headers,
        json={
            "definition": {
                "widgets": [
                    {
                        "id": "kept",
                        "type": "stat",
                        "binding": {
                            "source": "query",
                            "sql": "SELECT count(*) AS n FROM tasks",
                        },
                    }
                ]
            },
            "config": {
                "widgets": {"kept": {"counter_id": 7}, "gone": {"counter_id": 9}}
            },
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["config"] == {"widgets": {"kept": {"counter_id": 7}}}


async def test_delete_dashboard(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)
    dashboard = await create_dashboard(session, a.initiative, a.user)

    response = await client.delete(
        a.g(f"/dashboards/{dashboard.id}"), headers=a.headers
    )
    assert response.status_code == 204

    listing = await client.get(a.g("/dashboards/"), headers=a.headers)
    assert listing.json()["items"] == []


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


async def test_member_without_create_permission_is_refused(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.post(
        b.g("/dashboards/"),
        headers=b.headers,
        json={"name": "Mine", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 403


async def test_unshared_dashboard_is_invisible_to_other_members(
    client: AsyncClient, acting_user, session
):
    """DAC is the final gate: a co-member who holds no grant can neither list
    nor read it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)
    dashboard = await create_dashboard(session, a.initiative, a.user)
    await strip_non_owner_grants(session, dashboard, a.user.id)

    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    listing = await client.get(b.g("/dashboards/"), headers=b.headers)
    assert listing.status_code == 200
    assert listing.json()["items"] == []

    detail = await client.get(b.g(f"/dashboards/{dashboard.id}"), headers=b.headers)
    assert detail.status_code in (403, 404)


async def test_read_grant_cannot_write(client: AsyncClient, acting_user, session):
    """A viewer may look at the canvas but not re-author it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)
    dashboard = await create_dashboard(session, a.initiative, a.user)

    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    assert (
        await client.get(b.g(f"/dashboards/{dashboard.id}"), headers=b.headers)
    ).status_code == 200

    response = await client.patch(
        b.g(f"/dashboards/{dashboard.id}"),
        headers=b.headers,
        json={"name": "Hijacked"},
    )
    assert response.status_code == 403


async def test_non_member_of_initiative_cannot_see_dashboard(
    client: AsyncClient, acting_user, session
):
    """Initiative isolation is the hard boundary — a guild member outside the
    initiative gets nothing, even with a guild role."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)
    dashboard = await create_dashboard(session, a.initiative, a.user)

    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

    response = await client.get(b.g(f"/dashboards/{dashboard.id}"), headers=b.headers)
    assert response.status_code in (403, 404)


# --- widget catalog --------------------------------------------------------
#
# The catalog is what stops the editor's palette from carrying a second copy of
# the widget vocabulary, so its job is to be a faithful projection of
# WIDGET_SPECS rather than a hand-maintained list.


async def test_widget_catalog_projects_the_registry(
    client: AsyncClient, acting_user
) -> None:
    from app.services.tenant.dashboard_definition import WIDGET_PRESETS, WIDGET_SPECS

    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    response = await client.get(a.g("/dashboards/widget-catalog"), headers=a.headers)
    assert response.status_code == 200
    body = response.json()

    assert {entry["type"] for entry in body["widgets"]} == set(WIDGET_SPECS)
    assert {entry["name"] for entry in body["presets"]} == set(WIDGET_PRESETS)

    for entry in body["widgets"]:
        spec = WIDGET_SPECS[entry["type"]]
        assert (entry["min_w"], entry["min_h"]) == (spec.min_w, spec.min_h)
        assert (entry["default_w"], entry["default_h"]) == (
            spec.default_w,
            spec.default_h,
        )
        # Served in declared order, because inference walks the slots in it.
        assert [slot["name"] for slot in entry["shape"]] == [
            slot.name for slot in spec.shape
        ]
        for served, slot in zip(entry["shape"], spec.shape):
            assert set(served["types"]) == {kind.value for kind in slot.types}
            assert served["required"] is slot.required
            assert served["repeatable"] is slot.repeatable
        assert {option["key"] for option in entry["options"]} == set(spec.options)
        for option in entry["options"]:
            declared = spec.options[option["key"]]
            # Served in declared order, not sorted: a time scale reads
            # day -> quarter, and the default is stated rather than taken from
            # whichever value happens to sort first.
            assert option["values"] == list(declared.values)
            assert option["default"] == declared.default
            assert option["kind"] == declared.kind


async def test_widget_catalog_presets_resolve_to_primitives(
    client: AsyncClient, acting_user
) -> None:
    """A preset that named a primitive we don't ship would put an unrenderable
    entry in the palette."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    response = await client.get(a.g("/dashboards/widget-catalog"), headers=a.headers)
    body = response.json()

    primitives = {entry["type"] for entry in body["widgets"]}
    for preset in body["presets"]:
        assert preset["primitive"] in primitives


async def test_widget_catalog_requires_guild_membership(
    client: AsyncClient, acting_user, session
) -> None:
    """Static metadata, but still addressed inside a guild — an outsider gets
    the same 403 every other dashboard route gives."""
    from app.testing import create_guild

    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    other = await create_guild(session)
    response = await client.get(
        f"/api/v1/c/{other.id}/dashboards/widget-catalog", headers=a.headers
    )
    assert response.status_code == 403


async def test_widget_catalog_path_is_not_read_as_an_id(
    client: AsyncClient, acting_user
) -> None:
    """The literal route has to win over /{dashboard_id}, which would otherwise
    swallow it and 422 on the int parse."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    response = await client.get(a.g("/dashboards/widget-catalog"), headers=a.headers)
    assert response.status_code == 200
    assert "widgets" in response.json()


async def test_dashboard_counts_by_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Grouped counts mirror the list: DAC-visible dashboards in
    dashboards-enabled initiatives only."""
    from app.testing import create_initiative

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)
    disabled_initiative = await create_initiative(
        session, a.guild, a.user, dashboards_enabled=False
    )

    await create_dashboard(session, a.initiative, a.user, name="Health")
    await create_dashboard(session, a.initiative, a.user, name="Flow")
    await create_dashboard(session, disabled_initiative, a.user, name="Hidden")

    response = await client.get(a.g("/tools/counts/by-initiative"), headers=a.headers)
    assert response.status_code == 200, response.text
    assert response.json()["counts"]["dashboard"] == {str(a.initiative.id): 2}
