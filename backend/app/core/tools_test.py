"""Coverage tests — every tool is wired into every per-tool surface.

The tools are uniform, so instead of a mirror registry these assert directly
that each real surface (the soft-delete model list, the trash listing, the tag
and comment registries, the mounted routes) covers the whole ``Tool`` enum /
every soft-deletable model. A new tool — or a new soft-delete model — that
forgets one of them fails here. This is the "confirm all tools have similar
surface coverage" guarantee, kept honest against the actual sources rather than
a re-declared list.

The plain ``set(registry) == set(enum)`` rows live together in
``app/core/registry_coverage_test.py``, one row per registry.
"""

import pytest

from app.core.tools import Tool

pytestmark = pytest.mark.always


def test_trash_listing_covers_every_soft_delete_model():
    # Every soft-deletable model must be listable in the trash can, else a trashed
    # row of that type is invisible (and unrestorable) to the user.
    from app.api.v1.tenant_endpoints.trash import ENTITY_REGISTRY
    from app.db.soft_delete_filter import SOFT_DELETE_MODELS

    listed = {model for model, _name_field in ENTITY_REGISTRY.values()}
    assert set(SOFT_DELETE_MODELS) <= listed


def test_every_builtin_role_answers_for_every_permission_key():
    # The per-role tables are written out by hand, one entry per key. A tool
    # added to the enum gives every built-in role two more keys to answer for,
    # and a role that is missing one fails here.
    from app.models.tenant.initiative import BUILTIN_ROLE_PERMISSIONS, PermissionKey

    for role_permissions in BUILTIN_ROLE_PERMISSIONS.values():
        assert set(role_permissions) == set(PermissionKey)


def test_kinds_keep_their_codes_and_live_where_their_sharing_says():
    """Codes are the high bits of every stored node id.

    Changing one silently re-encodes a kind: rows written before keep the old
    value, rows after get the new one, and nothing errors. This is the test that
    holds that rule, because the database cannot. A kind inside a tool names
    the tool whose sharing the policies already gate it by; one in no one
    instance of its tool has no sharing to be gated by.
    """
    from app.core.tools import KINDS
    from app.db.initiative_rls import governing_path

    codes = [kind.code for kind in KINDS.values()]
    assert len(codes) == len(set(codes))
    assert all(code > 0 for code in codes)
    for kind in KINDS.values():
        if kind.standalone:
            assert governing_path(kind.table) is None, kind.value
        elif kind.parent is not None:
            assert governing_path(kind.table) == (
                kind.parent,
                ((kind.parent_column, kind.parent.plural),),
            ), kind.value


def test_every_tool_has_an_initiative_master_switch():
    # EVERY tool has an initiative-level `{plural}_enabled` master switch (model
    # column + read/create/update schema fields) — projects and files
    # included, which is the whole of making them optional.
    from app.models.tenant.initiative import Initiative
    from app.schemas.tenant.initiative import InitiativeBase, InitiativeUpdate

    switches = {t.view_permission for t in Tool}
    model_fields = set(Initiative.model_fields)
    schema_fields = set(InitiativeBase.model_fields)
    update_fields = set(InitiativeUpdate.model_fields)
    assert switches <= model_fields
    assert switches <= schema_fields
    assert switches <= update_fields


def test_an_initiative_starts_with_projects_and_files_on():
    # Optional is not the same as off. An initiative created without an opinion
    # about its tools is the one people already had, so the two that used to be
    # unconditional keep arriving switched on and everything else stays opt-in.
    from app.core.tools import DEFAULT_ENABLED_TOOLS, Tool
    from app.models.tenant.initiative import Initiative
    from app.schemas.tenant.initiative import InitiativeBase

    assert DEFAULT_ENABLED_TOOLS == {Tool.project, Tool.file}
    for tool in Tool:
        expected = tool in DEFAULT_ENABLED_TOOLS
        assert Initiative.model_fields[tool.view_permission].default is expected
        assert InitiativeBase.model_fields[tool.view_permission].default is expected


def test_every_tool_is_commentable():
    # Comments span EVERY tool plus the content-level extras: the service
    # registry, the comments table's parent FKs, the RLS parent declaration,
    # and the create schema's target fields all agree. A new tool that forgets
    # its CommentTarget — or an extra that forgets its column — fails here.
    from sqlalchemy import inspect as sa_inspect

    from app.core.tools import COMMENTABLE_EXTRAS, COMMENT_TARGETS, KINDS
    from app.db.initiative_rls import _COMMENT_PARENTS
    from app.models.tenant.comment import Comment
    from app.schemas.tenant.comment import COMMENT_TARGET_FIELDS
    from app.services.tenant.comments import (
        COMMENT_PARENT_COLUMNS,
        EXTRA_COMMENT_TARGETS,
        TOOL_COMMENT_TARGETS,
    )

    assert set(TOOL_COMMENT_TARGETS) == set(Tool)
    # The extras are the ones that are NOT tools, and nothing is both.
    assert set(COMMENT_TARGETS) == set(COMMENTABLE_EXTRAS) | {t.value for t in Tool}
    assert not set(COMMENTABLE_EXTRAS) & {t.value for t in Tool}
    assert set(COMMENT_PARENT_COLUMNS) == {f"{target}_id" for target in COMMENT_TARGETS}
    assert set(EXTRA_COMMENT_TARGETS) == {f"{extra}_id" for extra in COMMENTABLE_EXTRAS}

    model_columns = {c.name for c in sa_inspect(Comment).persist_selectable.columns}
    assert set(COMMENT_PARENT_COLUMNS) <= model_columns

    assert {p.column for p in _COMMENT_PARENTS} == set(COMMENT_PARENT_COLUMNS)
    assert set(COMMENT_TARGET_FIELDS) == set(COMMENT_PARENT_COLUMNS)

    # Every extra names a tool to answer for it, and a real column to reach it
    # by — that is what makes a thread on something that is not a tool gated
    # like one — or answers for itself, as a kind no sharing governs does.
    for column, extra in EXTRA_COMMENT_TARGETS.items():
        parent = next(p for p in _COMMENT_PARENTS if p.column == column)
        if parent.governed_by is None:
            assert KINDS[extra.kind].standalone, column
            continue
        assert parent.tool_fk is not None, column
        extra_columns = {
            c.name for c in sa_inspect(extra.model).persist_selectable.columns
        }
        assert parent.tool_fk in extra_columns, column
        assert extra.title_field in extra_columns, column


def test_every_tool_row_is_written_without_returning():
    # A tool row is written before anything has been shared with anybody, so it
    # cannot be read back in the statement that writes it — the sharing policy
    # is what a RETURNING clause would be answered by, and at that instant the
    # answer is no. Turning implicit RETURNING off makes the id come from the
    # sequence first, so the INSERT stands alone. A new tool that forgets this
    # cannot be created at all; it fails here first.
    from sqlmodel import SQLModel

    import app.db.base  # noqa: F401  (populates the metadata)

    for tool in Tool:
        table = SQLModel.metadata.tables[tool.plural]
        assert table.implicit_returning is False, tool


def test_every_tool_records_where_it_came_from():
    # Every tool has a marketplace, and installing a listing imports a copy
    # that records the listing it came from. A tool whose table lacks the pair
    # would install with nowhere to put it.
    from sqlmodel import SQLModel

    import app.db.base  # noqa: F401  (populates the metadata)
    from app.models.tenant._mixins import ListingProvenanceMixin, tool_models

    models = tool_models()
    for tool in Tool:
        model = models[tool.plural]
        assert issubclass(model, ListingProvenanceMixin), tool
        columns = SQLModel.metadata.tables[tool.plural].columns
        assert {"listing_uid", "listing_version"} <= set(columns.keys()), tool


def test_every_tool_carries_the_comment_switch():
    # Every tool can turn its own thread off: the column on the content table
    # and the flag on the read schema are spelled the same on all six, and the
    # generic route that sets it takes the Tool enum as its path param. A new
    # tool that forgets the mixin — or a read schema that never exposes it —
    # fails here.
    from sqlalchemy import inspect as sa_inspect

    from app.main import app
    from app.models.tenant._mixins import CommentsToggleMixin
    from app.services.tenant.comments import TOOL_COMMENT_TARGETS

    for tool, target in TOOL_COMMENT_TARGETS.items():
        assert issubclass(target.model, CommentsToggleMixin), tool
        columns = {c.name for c in sa_inspect(target.model).persist_selectable.columns}
        assert "comments_enabled" in columns, tool

    routes = {getattr(route, "path", "") for route in app.routes}
    assert any(path.endswith("/tools/{tool}/{tool_id}/comments") for path in routes)


def test_every_tool_read_schema_reports_the_comment_switch():
    # The frontend hides a thread by reading this flag off the entity it has
    # already loaded, so every tool's detail response must carry it. Read from
    # the served OpenAPI schema — the response models the routes actually
    # return — rather than a hand-kept list of schema classes.
    import re

    from app.main import app

    schema = app.openapi()
    for tool in Tool:
        pattern = re.compile(
            r"^/api/v1/c/\{community_id\}/"
            + re.escape(tool.route_segment)
            + r"/\{\w+\}$"
        )
        detail = next(
            (
                path
                for path, ops in schema["paths"].items()
                if pattern.match(path) and "get" in ops
            ),
            None,
        )
        assert detail is not None, tool
        ref = schema["paths"][detail]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        model = schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]
        assert "comments_enabled" in model["properties"], tool


def test_tag_link_specs_carry_the_uniform_contract():
    # Every taggable entity honors the structural contract everything derives
    # from: a model, and an endpoint kind whose table is that model's. A tag
    # assignment is a ``tagged_with`` edge in ``relationships`` now, so there is
    # no junction to check — what replaces it is that both halves of the spec
    # agree, and that the kind is one an edge may actually name.
    from app.core.relationships import ENDPOINT_KINDS
    from app.services.tenant.tags import TAG_LINKS

    for name, spec in TAG_LINKS.items():
        assert spec.kind in ENDPOINT_KINDS, name
        assert ENDPOINT_KINDS[spec.kind].table == spec.entity.__tablename__, name
        assert spec.kind.value == name, name


def test_every_tag_target_has_a_spec():
    # Derived from the enum-backed TAG_TARGETS, so a new tool that forgets to
    # wire its tags fails here. Exact equality also catches a leftover spec for
    # a removed target.
    from app.core.tools import TAG_TARGETS
    from app.services.tenant.tags import TAG_LINKS

    assert set(TAG_LINKS) == set(TAG_TARGETS)


def test_a_tag_assignment_is_an_edge_like_any_other():
    # The one relation the whole tag layer reads and writes, and the direction
    # it is stored in: a tag is a label, so the edge describes the thing
    # carrying it and the tag is always the target.
    from app.core.relationships import SPECS, RelationshipType

    spec = SPECS[RelationshipType.tagged_with]
    assert not spec.symmetric, "a tagged thing and a tag are not interchangeable"
    assert not spec.transitive, "a tag of a tag is not a tag of the thing"


def test_the_generic_tool_tags_route_is_the_only_tool_set_tags_surface():
    # ONE generic route serves every tool — its {tool} path param is the Tool
    # enum itself, so a new member is covered with no new endpoint. The
    # content-level extras (tasks, events, queue items) take ``tag_ids`` on
    # their own PATCH; the exact equality means a re-added set-tags route
    # fails here.
    from app.main import app

    spec = app.openapi()
    put_tag_paths = {
        path
        for path, item in spec["paths"].items()
        if "put" in item and path.endswith("/tags")
    }
    generic = "/api/v1/c/{community_id}/tools/{tool}/{tool_id}/tags"
    assert put_tag_paths == {generic}

    tool_param = next(
        p for p in spec["paths"][generic]["put"]["parameters"] if p["name"] == "tool"
    )
    schema = tool_param["schema"]
    ref = schema.get("$ref") or schema["allOf"][0]["$ref"]
    enum_values = spec["components"]["schemas"][ref.rsplit("/", 1)[-1]]["enum"]
    assert set(enum_values) == {t.value for t in Tool}


def test_every_tool_mounts_its_list_route():
    # A tool's guild-wide list is mounted from TOOL_LISTS for every tool
    # (tenant_endpoints/tool_lists.py), which also feeds the one sidebar-counts
    # route. The operation id is asserted too: it is the generated
    # frontend client's function name, so a tool that loses its list — or
    # gains a hand-written copy somewhere else — fails here rather than
    # silently changing the client.
    from app.api.v1.tenant_endpoints.tool_lists import TOOL_LISTS
    from app.main import app

    assert set(TOOL_LISTS) == set(Tool)

    spec = app.openapi()
    for tool in Tool:
        segment = tool.route_segment
        listing = spec["paths"][f"/api/v1/c/{{community_id}}/{segment}/"]["get"]
        assert listing["operationId"] == f"list_{tool.plural}", tool
        # Every tool is taggable, so every list narrows by tag.
        assert "tag_ids" in {p["name"] for p in listing["parameters"]}, tool


def test_every_tool_mounts_the_grants_route():
    # Sharing is one route, mounted from the resource-access registry for every
    # tool (tenant_endpoints/tool_grants.py). The exact equality means a tool
    # that loses it — or a hand-written copy added back somewhere else — fails
    # here. The operation id is asserted too: it is the generated frontend
    # client's function name.
    from app.api.resource_access import RESOURCE_ACCESS
    from app.main import app

    spec = app.openapi()
    mounted = {path for path in spec["paths"] if path.endswith("/grants")}
    expected = {
        f"/api/v1/c/{{community_id}}/{tool.route_segment}"
        f"/{{{RESOURCE_ACCESS[tool].path_param}}}/grants"
        for tool in Tool
    }
    assert mounted == expected

    for tool in Tool:
        path = (
            f"/api/v1/c/{{community_id}}/{tool.route_segment}"
            f"/{{{RESOURCE_ACCESS[tool].path_param}}}/grants"
        )
        item = spec["paths"][path]
        assert set(item) == {"put"}, tool
        assert item["put"]["operationId"] == f"set_{tool.value}_grants", tool


def test_every_tool_mounts_its_cross_guild_list_route():
    # The My Tools page's list is one route, mounted from MY_TOOL_LISTS for
    # every tool (tenant_endpoints/me_tools.py). Projects, files and
    # calendars each carried a hand-written copy of it until this registry took
    # them over, so the count is asserted as well as the presence: a tool that
    # loses its list, or grows a second one anywhere else under /me, fails here
    # rather than silently changing the client. The operation id is the
    # generated frontend client's function name.
    from app.api.v1.tenant_endpoints.me_tools import MY_TOOL_LISTS
    from app.main import app

    assert set(MY_TOOL_LISTS) == set(Tool)

    spec = app.openapi()
    operation_ids = [
        operation["operationId"]
        for item in spec["paths"].values()
        for operation in item.values()
    ]
    for tool in Tool:
        path = f"/api/v1/me/{tool.route_segment}"
        listing = spec["paths"][path]["get"]
        name = f"list_my_{tool.plural}"
        assert listing["operationId"] == name, tool
        assert operation_ids.count(name) == 1, tool


def test_tool_models_spell_the_shared_columns_the_same():
    # The facts every tool table carries spell the same on each of them: one
    # display column called `name` (files said `title` until 0191), and
    # the shared scope/author/lifecycle columns under their canonical names.
    # A new tool that renames one of these — or labels rows through a synonym
    # like `title`/`label` — fails here. Sub-resources (tasks, queue items,
    # calendar events) are not tools and keep their own words.
    from app.services.tenant.tags import TOOL_TAG_LINKS

    shared_columns = {
        "id",
        "initiative_id",
        "name",
        "created_by",
        "created_at",
        "updated_at",
        "deleted_at",
        "deleted_by",
        "purge_at",
    }
    synonyms = {"title", "label"}
    for tool in Tool:
        model = TOOL_TAG_LINKS[tool].entity
        columns = {c.name for c in model.__table__.columns}
        missing = shared_columns - columns
        assert not missing, f"{tool.value}: missing shared columns {missing}"
        assert not (synonyms & columns), (
            f"{tool.value}: {synonyms & columns} duplicates a shared concept"
        )
        assert model.display_field() == "name", tool.value


def test_export_adapters_cover_exactly_the_bulk_export_tools():
    """The export-engine adapter registry and the tool registry must agree:
    every BULK_EXPORT_TOOLS member has an adapter keyed by its kebab-singular
    source name, and the only non-tool source is the tasks sub-resource. A
    new exportable tool (or a renamed source) fails here instead of shipping
    a bulk-export flag with no engine behind it."""
    from app.core.tools import BULK_EXPORT_TOOLS, Tool, tool_export_source
    from app.services.export.adapters import ADAPTERS

    derived = {tool_export_source(tool) for tool in BULK_EXPORT_TOOLS}
    extra = set(ADAPTERS) - derived
    assert derived <= set(ADAPTERS), f"missing adapters for {derived - set(ADAPTERS)}"
    # "tasks" and "events" are the filterable task and event lists, not a
    # Tool; "initiative"/"community" are the aggregate backup/report scopes.
    allowed = {"tasks", "events", "initiative", "community"}
    assert extra == allowed, f"unregistered export sources: {extra - allowed}"
    # Tools without the flag must not silently grow an adapter either.
    unflagged = {
        tool_export_source(t) for t in Tool if t not in BULK_EXPORT_TOOLS
    } & set(ADAPTERS)
    assert not unflagged, (
        f"adapter exists but tool not in BULK_EXPORT_TOOLS: {unflagged}"
    )


def test_importers_cover_exactly_the_portable_tools():
    """Export and import are ONE capability — a tool's JSON envelope
    round-trips through both — so the importer registry answers to the same set
    the export side writes, keyed by the same derived discriminator.

    A tool with an export adapter and no importer emits an envelope the
    envelope endpoint refuses as an unknown type and a backup restore skips.
    The frontend derives its import affordance from the same set
    (``toolForEnvelopeType``), so it offers whatever is listed here.
    """
    from app.core.tools import BULK_EXPORT_TOOLS, Tool, tool_envelope_type
    from app.services.import_engine.importers import IMPORTERS

    derived = {tool_envelope_type(tool) for tool in BULK_EXPORT_TOOLS}
    assert tool_envelope_type(Tool.counter_group) == "initiative-counter-group"
    assert set(IMPORTERS) == derived, (
        f"missing importers for {sorted(derived - set(IMPORTERS))}; "
        f"unregistered importer types {sorted(set(IMPORTERS) - derived)}"
    )
    # Keyed by its own declared attribute, so the registry dict and the class
    # cannot disagree about which type an importer answers to.
    for envelope_type, importer in IMPORTERS.items():
        assert importer.envelope_type == envelope_type
    # A non-portable tool must not quietly grow one either.
    unflagged = {
        tool_envelope_type(t) for t in Tool if t not in BULK_EXPORT_TOOLS
    } & set(IMPORTERS)
    assert not unflagged, (
        f"importer exists but tool not in BULK_EXPORT_TOOLS: {sorted(unflagged)}"
    )
