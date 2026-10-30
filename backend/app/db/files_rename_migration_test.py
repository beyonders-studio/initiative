"""Migrations 20261006_0464 and 20261006_0465 call the documents tool files.

Loaded by path and run on a guild the test builds: down to the names an older
release wrote, rows written that way, then up, down and up again, the way
``stored_values_migration_test`` runs its revisions.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.models.platform.notification import NotificationType
from app.services.platform import notice_outbox, user_notifications
from app.testing import (
    create_dashboard,
    create_export_job,
    create_file,
    create_guild,
    create_guild_plugin,
    create_initiative,
    create_marketplace_listing,
    create_plugin_service_registration,
    create_project,
    create_property_definition,
    create_property_value,
    create_relationship,
    create_user,
)

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load(name: str) -> ModuleType:
    path = _VERSIONS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _rows(session, sql: str, **params: Any) -> list[tuple]:
    result = await (await session.connection()).execute(text(sql), params)
    return [tuple(row) for row in result.all()]


# A statement's quoted values and its output aliases are left as written; the
# names it reads move, quoted or not.
_OLD_STATEMENT = (
    'SELECT f.name AS "documents", f."document_type" FROM "documents" f '
    "JOIN documents d ON d.id = f.id WHERE f.name <> 'documents'"
)
_NEW_STATEMENT = (
    'SELECT f.name AS "documents", f."file_type" FROM "files" f '
    "JOIN files d ON d.id = f.id WHERE f.name <> 'documents'"
)
#: A plug-in widget's parameters are the plug-in's, whatever they are called.
_PLUGIN_BINDING = {"source": "plugin", "params": {"document_id": 5}}


def _guild_runner(schema: str):
    """Revision 0464 one way or the other, on one guild's schema only. The
    metadata store (20261027_0550), the galleries conversion (20261027_0546)
    and the data jobs table (20261030_0564) come off first and go back last:
    the checks 0464 restates name the permissions as they were then, and it
    respells the exports in the table they had then."""
    files = _load("20261006_0464_documents_are_files.py")
    collections = _load("20261027_0546_galleries_are_collections.py")
    metadata = _load("20261027_0550_metadata_is_one_store.py")
    data_jobs = _load("20261030_0564_imports_and_exports_are_data_jobs.py")

    def run(forward: bool):
        def apply(sync_session) -> None:
            bind = sync_session.connection()

            def in_schema(step) -> None:
                bind.execute(
                    text("SELECT set_config('search_path', :sp, true)"),
                    {"sp": f"{schema}, public"},
                )
                step()

            with Operations.context(MigrationContext.configure(bind)):
                if forward:
                    files._convert(bind, True, in_schema)
                    collections._convert(bind, True, in_schema)
                    in_schema(lambda: metadata._apply(True))
                    in_schema(data_jobs._upgrade_schema)
                else:
                    in_schema(data_jobs._downgrade_schema)
                    in_schema(lambda: metadata._apply(False))
                    collections._convert(bind, False, in_schema)
                    files._convert(bind, False, in_schema)

        return apply

    return run


async def _guild_values(session, schema: str, ids: dict[str, int]) -> dict:
    s = f'"{schema}"'
    return {
        "grants": await _rows(
            session,
            f"SELECT DISTINCT resource_type FROM {s}.resource_grants "
            "WHERE resource_id = :id AND resource_type IN ('file', 'document')",
            id=ids["file"],
        ),
        # The values' table, by the name it has on either side.
        "property": await _rows(
            session,
            "SELECT entity_type FROM "
            + (
                await _rows(
                    session,
                    f"SELECT COALESCE(to_regclass('{s}.metadata_values'), "
                    f"to_regclass('{s}.property_values'))::text",
                )
            )[0][0],
        ),
        "edge": await _rows(
            session,
            f"SELECT source_type, target_type, source_node, target_node "
            f"FROM {s}.relationships",
        ),
        "search": await _rows(
            session,
            f"SELECT DISTINCT entity_type, dac_tool FROM {s}.search_entries "
            "WHERE entity_id = :id AND entity_type IN ('file', 'document')",
            id=ids["file"],
        ),
        "permissions": await _rows(
            session,
            f"SELECT DISTINCT permission_key FROM {s}.initiative_role_permissions "
            "WHERE permission_key ~ '(file|document)' ORDER BY 1",
        ),
        "outbox": await _rows(
            session,
            f"SELECT resource_type, parents, changed FROM {s}.event_outbox "
            "WHERE id = :id",
            id=ids["outbox"],
        ),
        "webhook": await _rows(
            session, f"SELECT event_types, fields FROM {s}.webhook_subscriptions"
        ),
        "plugin": await _rows(
            session, f"SELECT granted_scopes, definition FROM {s}.guild_plugins"
        ),
        "dashboard": await _rows(
            session,
            f"SELECT definition, config FROM {s}.dashboards WHERE id = :id",
            id=ids["dashboard"],
        ),
        # The one export, in the table it has on either side; the data jobs
        # table gives it a new id.
        "export": await _rows(
            session,
            "SELECT source, params FROM "
            + (
                await _rows(
                    session,
                    f"SELECT COALESCE(to_regclass('{s}.export_jobs'), "
                    f"to_regclass('{s}.data_jobs'))::text",
                )
            )[0][0],
        ),
    }


async def test_guild_values_say_file_and_back(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    file = await create_file(session, initiative, user)
    definition = await create_property_definition(session, initiative)
    await create_property_value(session, file, definition, value_text="kept")
    await create_relationship(
        session,
        guild,
        source=(SearchEntityType.project, project.id),
        target=(SearchEntityType.file, file.id),
    )
    plugin_definition = {"service": {"scopes": ["documents:read", "tasks:read"]}}
    await create_guild_plugin(
        session,
        guild,
        user,
        definition=plugin_definition,
        granted_scopes=["documents:read", "documents:write"],
    )
    sheet = {"source": "sheet_range", "document_id": file.id, "range": "A1:B2"}
    dashboard = await create_dashboard(
        session,
        initiative,
        user,
        definition={
            "widgets": [
                {"id": "w1", "binding": {"source": "query", "sql": _OLD_STATEMENT}},
                {"id": "w2", "binding": sheet},
                {"id": "w3", "binding": {"entity": "document"}},
                {"id": "w4", "binding": _PLUGIN_BINDING},
            ]
        },
        config={
            "widgets": {
                "w2": {"document_id": file.id, "range": "A1:B2"},
                "w4": {"document_id": 5},
            }
        },
    )
    await create_export_job(
        session,
        guild,
        user,
        source="document",
        params={"document_ids": [file.id], "formats": {"document": "pdf"}},
    )
    await session.commit()

    run = _guild_runner(schema)

    try:
        await session.run_sync(run(False))
        outbox_id = (
            await _rows(
                session,
                f'INSERT INTO "{schema}".event_outbox (txn_id, occurred_at, '
                "resource_type, resource_id, action, parents, changed) VALUES "
                "(1, now(), 'documents', :id, 'updated', "
                "CAST(:parents AS jsonb), ARRAY['document_type', 'name']) "
                "RETURNING id",
                id=file.id,
                parents=json.dumps([{"id": file.id, "type": "documents"}]),
            )
        )[0][0]
        await (await session.connection()).execute(
            text(
                f'INSERT INTO "{schema}".webhook_subscriptions (target_url, '
                "hmac_secret, event_types, fields) VALUES ('https://hook.test', "
                "'s', ARRAY['documents.updated', 'tasks.created'], "
                "ARRAY['document_type', 'name'])"
            )
        )
        await session.commit()
        ids = {
            "file": file.id,
            "outbox": outbox_id,
            "dashboard": dashboard.id,
        }
        old = await _guild_values(session, schema, ids)

        await session.run_sync(run(True))
        await session.commit()
        node = (6 << 32) | file.id
        new = await _guild_values(session, schema, ids)
        assert new["grants"] == [("file",)]
        assert new["property"] == [("file",)]
        ((source, target, *nodes),) = new["edge"]
        assert {source, target} == {"project", "file"} and node in nodes
        # The node ids are computed, and the file kind keeps its code.
        assert [edge[2:] for edge in new["edge"]] == [edge[2:] for edge in old["edge"]]
        assert new["search"] == [("file", "file")]
        assert new["permissions"] == [("create_files",), ("files_enabled",)]
        assert new["outbox"] == [
            ("files", [{"id": file.id, "type": "files"}], ["file_type", "name"])
        ]
        assert new["webhook"] == [
            (["files.updated", "tasks.created"], ["file_type", "name"])
        ]
        assert new["plugin"] == [
            (
                ["files:read", "files:write"],
                {"service": {"scopes": ["files:read", "tasks:read"]}},
            )
        ]
        assert new["dashboard"] == [
            (
                {
                    "widgets": [
                        {
                            "id": "w1",
                            "binding": {"source": "query", "sql": _NEW_STATEMENT},
                        },
                        {
                            "id": "w2",
                            "binding": {
                                "source": "sheet_range",
                                "file_id": file.id,
                                "range": "A1:B2",
                            },
                        },
                        {"id": "w3", "binding": {"entity": "file"}},
                        {"id": "w4", "binding": _PLUGIN_BINDING},
                    ]
                },
                {
                    "widgets": {
                        "w2": {"file_id": file.id, "range": "A1:B2"},
                        "w4": {"document_id": 5},
                    }
                },
            )
        ]
        assert new["export"] == [
            ("file", {"file_ids": [file.id], "formats": {"file": "pdf"}})
        ]

        await session.run_sync(run(False))
        await session.commit()
        assert await _guild_values(session, schema, ids) == old
        assert old["grants"] == [("document",)]
    finally:
        await session.run_sync(run(True))
        await session.commit()


async def test_an_edge_between_two_files_is_respelled(session) -> None:
    """Both ends name the kind, and the rewrite reaches them one column at a
    time, so the code reads both spellings while it does."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    first = await create_file(session, initiative, user)
    second = await create_file(session, initiative, user)
    await create_relationship(
        session,
        guild,
        source=(SearchEntityType.file, first.id),
        target=(SearchEntityType.file, second.id),
        relationship_type=RelationshipType.references,
    )
    await session.commit()
    run = _guild_runner(schema)
    edge = (
        "SELECT source_type, target_type, source_node, target_node "
        f'FROM "{schema}".relationships'
    )
    nodes = ((6 << 32) | first.id, (6 << 32) | second.id)
    code = "SELECT public.relationship_kind_code(:kind)"

    try:
        await session.run_sync(run(False))
        await session.commit()
        assert await _rows(session, edge) == [("document", "document", *nodes)]
        assert await _rows(session, code, kind="file") == [(None,)]
    finally:
        # A failed step aborts the transaction; restore from a fresh one.
        await session.rollback()
        await session.run_sync(run(True))
        await session.commit()
    assert await _rows(session, edge) == [("file", "file", *nodes)]
    assert await _rows(session, code, kind="document") == [(None,)]


async def _public_values(session, user_id: int, registration_id: int) -> dict:
    return {
        "lines": await _rows(
            session,
            "SELECT tool, subject_type, CAST(data AS jsonb) FROM public.notifications "
            "WHERE user_id = :u ORDER BY id",
            u=user_id,
        ),
        "queued": await _rows(
            session,
            "SELECT data, push_data, rollup_key, email_link FROM public.notice_outbox "
            "WHERE user_id = :u",
            u=user_id,
        ),
        "ceiling": await _rows(
            session,
            "SELECT scope_ceiling FROM public.plugin_service_registrations "
            "WHERE id = :id",
            id=registration_id,
        ),
        "listings": await _rows(
            session,
            "SELECT l.public_id, l.kind, v.definition "
            "FROM public.marketplace_listings l "
            "JOIN public.marketplace_listing_versions v ON v.listing_id = l.id "
            "WHERE l.public_id LIKE 'rename.%' ORDER BY l.public_id",
        ),
    }


async def test_public_values_say_file_and_back(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    line = {
        "tool": "document",
        "subject_type": "document",
        "entity_type": "document",
        "entity_id": 5,
        "target_path": "/go/document/5",
        "smart_link": "https://app.test/navigate?community_id=1&target=%2Fgo%2Fdocument%2F5",
        "rollup_key": "document-body:5",
    }
    page = {"target_path": "/c/1/i/2/documents/5", "rollup_key": "document:5"}
    for data in (line, page):
        await user_notifications.create_notification(
            session,
            user_id=user.id,
            notification_type=NotificationType.mention,
            data=data,
        )
    await notice_outbox.enqueue(
        session,
        [
            notice_outbox.row(
                user.id,
                guild.id,
                NotificationType.mention,
                {"context_entity_type": "document", "target_path": "/go/document/5"},
                push_data={"target_path": "/go/document/5"},
            )
        ],
    )
    registration = await create_plugin_service_registration(
        session, scope_ceiling=["documents:read", "tasks:read"]
    )
    await (await session.connection()).execute(
        text(
            "UPDATE public.notifications SET tool = 'document', "
            "subject_type = 'document' WHERE user_id = :u"
        ),
        {"u": user.id},
    )
    await (await session.connection()).execute(
        text(
            "UPDATE public.notice_outbox SET rollup_key = 'document-body:5', "
            "email_link = 'https://app.test/navigate?target=%2Fgo%2Fdocument%2F5' "
            "WHERE user_id = :u"
        ),
        {"u": user.id},
    )
    # Published before the rename: a dashboard, a file listing and a plug-in.
    # Built valid, then written back the way the old build stored them.
    old_sheet = {"source": "sheet_range", "document_id": None, "range": "A1:B2"}
    dashboard_definition = {
        "type": "initiative-dashboard",
        "name": "Board",
        "definition": {
            "widgets": [
                {"id": "w1", "binding": {"source": "query", "sql": _OLD_STATEMENT}},
                {"id": "w2", "binding": old_sheet},
                {"id": "w4", "binding": _PLUGIN_BINDING},
            ]
        },
        "config": {"widgets": {"w2": {"document_id": 3}, "w4": {"document_id": 5}}},
    }
    file_definition = {
        "type": "initiative-document",
        "document_type": "native",
        "external_ref": "document:4",
    }
    plugin_definition = {"service": {"scopes": ["documents:read"]}}
    for uid, name, kind, body in (
        ("RENAMETEST0001", "rename.dashboard", "dashboard", dashboard_definition),
        ("RENAMETEST0002", "rename.file", "document", file_definition),
        ("RENAMETEST0003", "rename.plugin", "plugin", plugin_definition),
    ):
        listing = await create_marketplace_listing(session, uid=uid, public_id=name)
        await (await session.connection()).execute(
            text("UPDATE public.marketplace_listings SET kind = :k WHERE id = :id"),
            {"k": kind, "id": listing.id},
        )
        await (await session.connection()).execute(
            text(
                "UPDATE public.marketplace_listing_versions "
                "SET definition = CAST(:d AS jsonb) WHERE listing_id = :id"
            ),
            {"d": json.dumps(body), "id": listing.id},
        )
    for key in ("documents:view-mode", "my-tasks"):
        await (await session.connection()).execute(
            text(
                "INSERT INTO public.user_view_preferences "
                "(user_id, scope_key, value, updated_at) "
                "VALUES (:u, :k, CAST('{}' AS json), now())"
            ),
            {"u": user.id, "k": key},
        )
    await session.commit()
    migration = _load("20261006_0465_documents_are_files_in_public.py")
    old = await _public_values(session, user.id, registration.id)

    def run(step):
        def apply(sync_session) -> None:
            with Operations.context(
                MigrationContext.configure(sync_session.connection())
            ):
                step()

        return apply

    await session.run_sync(run(migration.upgrade))
    await session.commit()
    try:
        assert await _public_values(session, user.id, registration.id) == {
            "lines": [
                (
                    "file",
                    "file",
                    {
                        **line,
                        "tool": "file",
                        "subject_type": "file",
                        "entity_type": "file",
                        "target_path": "/go/file/5",
                        "smart_link": "https://app.test/navigate?community_id=1"
                        "&target=%2Fgo%2Ffile%2F5",
                        "rollup_key": "file-body:5",
                    },
                ),
                (
                    "file",
                    "file",
                    {"target_path": "/c/1/i/2/files/5", "rollup_key": "file:5"},
                ),
            ],
            "queued": [
                (
                    {"context_entity_type": "file", "target_path": "/go/file/5"},
                    {"target_path": "/go/file/5"},
                    "file-body:5",
                    "https://app.test/navigate?target=%2Fgo%2Ffile%2F5",
                )
            ],
            "ceiling": [(["files:read", "tasks:read"],)],
            "listings": [
                (
                    "rename.dashboard",
                    "dashboard",
                    {
                        "type": "initiative-dashboard",
                        "name": "Board",
                        "definition": {
                            "widgets": [
                                {
                                    "id": "w1",
                                    "binding": {
                                        "source": "query",
                                        "sql": _NEW_STATEMENT,
                                    },
                                },
                                {
                                    "id": "w2",
                                    "binding": {
                                        "source": "sheet_range",
                                        "file_id": None,
                                        "range": "A1:B2",
                                    },
                                },
                                {"id": "w4", "binding": _PLUGIN_BINDING},
                            ]
                        },
                        "config": {
                            "widgets": {
                                "w2": {"file_id": 3},
                                "w4": {"document_id": 5},
                            }
                        },
                    },
                ),
                (
                    "rename.file",
                    "file",
                    {
                        "type": "initiative-file",
                        "file_type": "native",
                        "external_ref": "file:4",
                    },
                ),
                # A plug-in manifest is its publisher's: refused, not rewritten.
                ("rename.plugin", "plugin", plugin_definition),
            ],
        }
        kept = await _rows(
            session,
            "SELECT scope_key FROM public.user_view_preferences WHERE user_id = :u",
            u=user.id,
        )
        assert kept == [("my-tasks",)]
    finally:
        await session.run_sync(run(migration.downgrade))
        await session.commit()
    assert await _public_values(session, user.id, registration.id) == old
    await session.run_sync(run(migration.upgrade))
    await session.commit()
