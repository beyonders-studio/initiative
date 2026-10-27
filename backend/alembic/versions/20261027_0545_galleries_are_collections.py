"""Galleries are collections

The galleries tool is gone: a gallery becomes a collection and each of its
pictures a file. In ``guild_template`` and every ``guild_<id>``:

* **Collections** — each ``galleries`` row is a ``collections`` row with the
  same id, initiative, name, description, author, dates, trash, archive, hold
  and comment state. Its cover picture's file is its ``cover_file_id``. Each
  converted collection lists its files the way the gallery did: masonry, grid
  and timeline shown, table hidden, opening on masonry (``tool_layouts``).
* **Files** — each ``gallery_images`` row that has a version is a ``files`` row
  in its gallery's initiative, named by its title, else its current version's
  filename, and typed by its current version's media type. The caption is
  dropped. A picture in a trashed or held gallery is trashed or held with it.
  Each ``gallery_image_versions`` row is a ``file_versions`` row pointing at
  the same blob, with the size the gallery measured; no bytes move and
  ``uploads`` is untouched. A version with no author takes the picture's,
  else the gallery's, else its owner's.
  A picture's version waits on a thumbnail, as 20261027_0543 left every
  picture uploaded before it, and the gallery's own thumbnails are left for
  nothing to show.
* **Membership** — a ``collection_files`` row adds each file to its gallery's
  collection, added by the picture's author when it was uploaded.
* **Sharing** — every ``resource_grants`` row of a gallery (each grantee and
  level, the owner included) is copied onto each of its pictures' files, and
  so is every guest invitation's grant; the gallery's own rows are removed.
* **What named a picture** names its file, through the picture → file map:
  property values, personal items, engagement levels, relationships (both
  ends), search entries, reactions, the reaction digest (its address is the
  file's ``/go/file/N``), holds, moderation reports and acts. A row naming a
  picture with no file is removed. A plug-in value on a picture is removed: a
  plug-in keeps values on items, and a file is not one.
* **What named a gallery** names its collection, same id: the same tables,
  and ``comments.gallery_id`` becomes ``comments.collection_id``. A gallery's
  bookmark is dropped (a collection is not a tool); the rest of the personal
  item stays.
* **Gone** — the gallery's layouts, its role permissions
  (``galleries_enabled``/``create_galleries``), its change-log rows and queued
  plug-in events, gallery event types and columns in webhook subscriptions (a
  subscription left with no event type is removed), the ``galleries:*``
  scopes an install was granted or its definition lists (and definition
  entries naming a gallery kind), and queued exports and imports of a gallery.
  A dashboard's statements are left as written.
* **Edges** — a symmetric relationship whose ends now sort the other way is
  stored with its ends swapped, as one written now would be.
* **Structure** — the CHECKs that list a kind or a permission are restated
  without the gallery values, with ``collection`` where the gallery kind was
  (not as a bookmark), the comment single-parent rule over ``collection_id``,
  and the list layouts masonry, grid and timeline. Then the three gallery
  tables, ``comments.gallery_id`` and ``initiatives.galleries_enabled`` are
  dropped. The policies and triggers that read them are dropped first; a start
  renders the policies of every table again from the registries, before any
  request is served, and the search generation is cleared so that start
  re-sweeps the index.

The writes run with each table's row security unforced and its user triggers
held, both restored in the same transaction once they are done.

In ``public``: ``public.relationship_kind_code`` reads both the gallery kinds
and ``collection`` (17) while the edges are rewritten, and only
``collection`` after; codes 7 and 8 are retired. A notification, and one still
queued, names the file or the collection the way the guild rows now do (a
picture's line whose picture has no file is removed). A plug-in service's
scope ceiling drops ``galleries:*``, gallery listings are removed, and the
saved gallery view preferences go.

The picture → file map lives in a temporary table for the length of the
revision (``pg_temp._gallery_picture_files``).

**Links in stored content** are written the way this build writes them, in
every schema, while the map is there (``app.core.legacy_references``): a
reference to a picture names its file, or is its words when the picture had no
file; one to a gallery names its collection; one to a ``document`` names the
file; a ``[[ ]]`` link (a ``wikilink`` node) is a reference to its file, or its
words; and ``#doc``, ``#gallery`` and ``#gallery-image`` in running text are
``#file``, ``#collection`` and ``#file``. That covers a Lexical file's and a
wiki page's body, a post's, and the markdown in every description, a task's
checklist and what an edit of it kept back, a task type's starting values,
queue item notes, event locations and comments. A body with a Yjs state that
holds an old spelling is read from that state through the editor, rewritten,
and written back into it as a change, so an editor still holding the document
merges with it; its JSON is the rewritten reading. A state the editor refuses
is cleared, and its JSON rewritten.

The downgrade puts back empty gallery tables, ``comments.gallery_id`` and
``initiatives.galleries_enabled``, removes every row that names a collection
(the comments on one included) and restates the CHECKs the old way. It does not
turn files back into pictures or links back into their old spellings, and
nothing it removed comes back.

Revision ID: 20261027_0545
Revises: 20261027_0544
Create Date: 2026-10-26
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from alembic import op
from pycrdt import Doc, Map, Text, XmlText
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.util import await_only

from app.core.legacy_references import rewrite_body, rewrite_text
from app.db.guild_migrations import run_for_each_guild_schema
import app.services.editor_engine as editor_engine

revision = "20261027_0545"
down_revision = "20261027_0544"
branch_labels = None
depends_on = None


_GALLERY_TABLES = ("galleries", "gallery_images", "gallery_image_versions")
#: Every guild table this revision reads or writes.
_TOUCHED = (
    *_GALLERY_TABLES,
    "collections",
    "collection_files",
    "files",
    "file_versions",
    "resource_grants",
    "guest_invite_grants",
    "property_values",
    "plugin_metadata",
    "personal_items",
    "engagement_levels",
    "relationships",
    "search_entries",
    "reactions",
    "reaction_digest_items",
    "content_holds",
    "moderation_reports",
    "moderation_actions",
    "comments",
    "initiatives",
    "tool_layouts",
    "initiative_role_permissions",
    "event_outbox",
    "plugin_event_outbox",
    "webhook_subscriptions",
    "webhook_deliveries",
    "guild_plugins",
    "export_jobs",
    "import_jobs",
)
#: (table, kind column, id column) for every row that names a thing by kind.
_NAMED_BY_KIND = (
    ("property_values", "entity_type", "entity_id"),
    ("personal_items", "entity_type", "entity_id"),
    ("engagement_levels", "entity_type", "entity_id"),
    ("relationships", "source_type", "source_id"),
    ("relationships", "target_type", "target_id"),
    ("reactions", "target_type", "target_id"),
    ("content_holds", "target_type", "target_id"),
    ("moderation_reports", "target_type", "target_id"),
    ("moderation_actions", "target_type", "target_id"),
)

_GALLERY = "gallery"
_PICTURE = "gallery_image"
_COLLECTION = "collection"
_PERMISSIONS = ("galleries_enabled", "create_galleries")
_SCOPES = ("galleries:read", "galleries:write")
#: The change log's resource names for the tool and its rows.
_RESOURCES = ("galleries", "gallery_images", "gallery_image_versions")
_EVENT_PREFIX = "galleries."
#: Columns a webhook subscription may list that only a gallery had.
_GALLERY_FIELDS = (
    "gallery_id",
    "gallery_image_id",
    "cover_image_id",
    "galleries_enabled",
    "caption",
)
#: Keys in an install's definition whose value names a kind.
_KIND_KEYS = ("entity", "kind", "tool", "itemKind")
#: How a converted collection lists its files: (kind, definition). Grid is
#: shown as shipped.
_COLLECTION_LAYOUTS = (
    ("masonry", {"hidden": False}),
    ("timeline", {"hidden": False}),
    ("table", {"hidden": True}),
    ("default", {"kind": "masonry"}),
)
_LIST_KINDS = ("masonry", "grid", "timeline")

#: A picture's format, from its current version's media type, as
#: 20261026_0540 names it for an uploaded file.
_PICTURE_FORMATS = (
    ("image/png", "png"),
    ("image/jpeg", "jpeg"),
    ("image/jpg", "jpeg"),
    ("image/gif", "gif"),
    ("image/webp", "webp"),
    ("image/svg+xml", "svg"),
)

#: The media types 20261027_0543 waits on a thumbnail for: a converted
#: picture's versions wait the same way, and the thumbnails sweep draws them.
_THUMBNAILED = ", ".join(
    f"'{media}'"
    for media in (
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/gif",
        "image/webp",
        "image/tiff",
    )
)

#: ``public.relationship_kind_code`` as 20261026_0541 left it.
_KIND_CODES_BEFORE = (
    ("calendar", 1),
    ("calendar_event", 2),
    ("counter", 3),
    ("counter_group", 4),
    ("dashboard", 5),
    ("file", 6),
    ("gallery", 7),
    ("gallery_image", 8),
    ("post", 9),
    ("project", 10),
    ("queue", 11),
    ("queue_item", 12),
    ("tag", 13),
    ("task", 14),
    ("wiki", 15),
    ("wiki_page", 16),
)
#: Both, while the edges are rewritten; what the downgrade leaves.
_KIND_CODES_EITHER = (*_KIND_CODES_BEFORE, (_COLLECTION, 17))
_KIND_CODES_AFTER = tuple(
    (kind, code)
    for kind, code in _KIND_CODES_EITHER
    if kind not in (_GALLERY, _PICTURE)
)

_MAP = "pg_temp._gallery_picture_files"
_IN_SCHEMA = "m.schema_name = current_schema()"
_CLEAR_SEARCH_GENERATION = "COMMENT ON TABLE search_entries IS NULL"

#: The CHECKs that hold a gallery value, and those that hold a collection one.
_GALLERY_CHECK = (
    r"'(gallery|gallery_image|galleries_enabled|create_galleries)'::|\mgallery_id\M"
)
_COLLECTION_CHECK = r"'(collection|masonry|grid|timeline)'::|\mcollection_id\M"
_PERMISSION_CHECK = "ck_initiative_role_permissions_permission_key"
_METADATA_CHECK = "ck_plugin_metadata_entity_type"
_BOOKMARK_CHECK = "ck_personal_items_bookmarked_tool"
_LAYOUT_TOOL_CHECK = "ck_tool_layouts_tool"
_LAYOUT_KIND_CHECK = "ck_tool_layouts_kind"
#: A symmetric edge is stored once, its lower node first: lifted while the
#: nodes are rewritten, since their codes and ids both move.
_SYMMETRIC_CHECK = "ck_relationships_symmetric_order"
_SYMMETRIC_TYPES = ("attached", "related_to")

_VIEW_PREFERENCES = (
    "scope_key ~ '(^|:)gallery(:|$)' OR scope_key = 'galleries' "
    "OR starts_with(scope_key, 'galleries:')"
)


def _kind_code_fn(codes: tuple[tuple[str, int], ...]) -> str:
    arms = " ".join(f"WHEN '{kind}' THEN {code}" for kind, code in codes)
    return f"""
        CREATE OR REPLACE FUNCTION public.relationship_kind_code(kind text)
        RETURNS bigint LANGUAGE sql IMMUTABLE STRICT AS $$
            SELECT (CASE kind {arms} END)::bigint
        $$
    """


def _case(expression: str, pairs: tuple[tuple[str, str], ...], otherwise: str) -> str:
    arms = " ".join(f"WHEN '{old}' THEN '{new}'" for old, new in pairs)
    return f"(CASE {expression} {arms} ELSE '{otherwise}' END)"


def _table_exists(bind: Connection, table: str) -> bool:
    return bool(bind.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar())


def _columns(bind: Connection, table: str) -> list[str]:
    return list(
        bind.execute(
            text(
                "SELECT attname FROM pg_attribute WHERE attrelid = to_regclass(:t) "
                "AND attnum > 0 AND NOT attisdropped ORDER BY attnum"
            ),
            {"t": table},
        ).scalars()
    )


@contextmanager
def _held(bind: Connection, tables: tuple[str, ...]) -> Iterator[None]:
    """Unforce each table's row security and hold its user triggers, restoring
    both on the tables still there afterwards. A failure rolls the whole
    revision back, these changes with it, so nothing is restored on that path:
    a statement there would only replace the error with "current transaction
    is aborted"."""
    forced: list[str] = []
    held: list[str] = []
    for table in tables:
        state = bind.execute(
            text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
        if state is None:
            continue
        if state:
            bind.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            forced.append(table)
        bind.exec_driver_sql(f"ALTER TABLE {table} DISABLE TRIGGER USER")
        held.append(table)
    yield
    for table in held:
        if _table_exists(bind, table):
            bind.exec_driver_sql(f"ALTER TABLE {table} ENABLE TRIGGER USER")
    for table in forced:
        if _table_exists(bind, table):
            bind.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


# --- CHECKs ------------------------------------------------------------------


def _drop_element(definition: str, value: str) -> str:
    """``definition`` without ``value`` in its array, however it is cast."""
    element = rf"\(?'{re.escape(value)}'::[a-z ]+\)?(?:::text)?"
    out = re.sub(rf",\s*{element}", "", definition, count=1)
    if out == definition:
        out = re.sub(rf"{element},\s*", "", definition, count=1)
    return out


def _add_elements(definition: str, values: tuple[str, ...]) -> str:
    """``definition`` with each of ``values`` it lacks at the head of its
    array."""
    added = "".join(f"'{v}'::text, " for v in values if f"'{v}'::" not in definition)
    return definition.replace("ARRAY[", f"ARRAY[{added}", 1)


def _respell_name(definition: str, old: str, new: str) -> str:
    """A column a CHECK lists: ``old`` becomes ``new``, or goes where ``new``
    is already listed."""
    if not re.search(rf"\b{old}\b", definition):
        return definition
    if not re.search(rf"\b{new}\b", definition):
        return re.sub(rf"\b{old}\b", new, definition)
    out = re.sub(rf",\s*{old}\b", "", definition, count=1)
    return out if out != definition else re.sub(rf"\b{old},\s*", "", definition)


def _forward_check(name: str, definition: str) -> str:
    for value in (_PICTURE, *_PERMISSIONS):
        definition = _drop_element(definition, value)
    if name == _BOOKMARK_CHECK or f"'{_COLLECTION}'::" in definition:
        definition = _drop_element(definition, _GALLERY)
    else:
        definition = definition.replace(f"'{_GALLERY}'::", f"'{_COLLECTION}'::")
    definition = _respell_name(definition, "gallery_id", "collection_id")
    if name == _LAYOUT_KIND_CHECK:
        definition = _add_elements(definition, _LIST_KINDS)
    return definition


def _backward_check(name: str, definition: str) -> str:
    for value in _LIST_KINDS:
        definition = _drop_element(definition, value)
    if f"'{_COLLECTION}'::" in definition:
        definition = definition.replace(f"'{_COLLECTION}'::", f"'{_GALLERY}'::")
        if name != _LAYOUT_TOOL_CHECK:
            definition = _add_elements(definition, (_PICTURE,))
    definition = _respell_name(definition, "collection_id", "gallery_id")
    if name in (_LAYOUT_KIND_CHECK, _METADATA_CHECK):
        definition = _add_elements(definition, (_PICTURE,))
    if name == _PERMISSION_CHECK:
        definition = _add_elements(definition, _PERMISSIONS)
    return definition


def _drop_checks(
    bind: Connection, pattern: str, names: tuple[str, ...] = ()
) -> dict[tuple[str, str], str]:
    """Drop the CHECKs in this schema whose definition matches ``pattern`` or
    whose name is one of ``names``, returning each one's definition."""
    rows = bind.execute(
        text(
            "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) "
            "FROM pg_constraint WHERE contype = 'c' "
            "AND connamespace = current_schema()::regnamespace "
            "AND (pg_get_constraintdef(oid) ~ :pattern "
            "OR CAST(conname AS text) = ANY(CAST(:names AS text[])))"
        ),
        {"pattern": pattern, "names": list(names)},
    ).all()
    dropped: dict[tuple[str, str], str] = {}
    for table, name, definition in rows:
        bind.exec_driver_sql(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
        dropped[(table, name)] = definition
    return dropped


def _restore_checks(
    bind: Connection,
    dropped: dict[tuple[str, str], str],
    restate: Callable[[str, str], str],
) -> None:
    for (table, name), definition in dropped.items():
        bind.exec_driver_sql(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} {restate(name, definition)}"
        )


# --- structure ---------------------------------------------------------------


_READERS = """
    SELECT 'POLICY', p.polname, p.polrelid::regclass::text, p.polrelid
    FROM pg_depend d JOIN pg_policy p ON p.oid = d.objid
    LEFT JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
    WHERE d.classid = 'pg_policy'::regclass AND d.refobjid = to_regclass(:t)
      AND (CAST(:c AS text) = '' OR a.attname = CAST(:c AS text))
    UNION
    SELECT 'TRIGGER', g.tgname, g.tgrelid::regclass::text, g.tgrelid
    FROM pg_depend d JOIN pg_trigger g ON g.oid = d.objid
    LEFT JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
    WHERE d.classid = 'pg_trigger'::regclass AND NOT g.tgisinternal
      AND d.refobjid = to_regclass(:t) AND (CAST(:c AS text) = '' OR a.attname = CAST(:c AS text))
"""


def _drop_readers(bind: Connection, tables: tuple[str, ...], column: str = "") -> None:
    """Drop the policies and triggers that read ``column`` of the one table,
    or, with no column, those on other tables that read any of ``tables``."""
    owned = {
        bind.execute(text("SELECT to_regclass(:t)::oid"), {"t": t}).scalar()
        for t in tables
    }
    for table in tables:
        if not _table_exists(bind, table):
            continue
        rows = bind.execute(text(_READERS), {"t": table, "c": column}).all()
        for what, name, on, relid in rows:
            if column or relid not in owned:
                bind.exec_driver_sql(f'DROP {what} IF EXISTS "{name}" ON {on}')


def _drop_gallery_structure(bind: Connection) -> None:
    _drop_readers(bind, ("comments",), "gallery_id")
    bind.exec_driver_sql("ALTER TABLE comments DROP COLUMN IF EXISTS gallery_id")
    _drop_readers(bind, ("initiatives",), "galleries_enabled")
    bind.exec_driver_sql(
        "ALTER TABLE initiatives DROP COLUMN IF EXISTS galleries_enabled"
    )
    _drop_readers(bind, _GALLERY_TABLES)
    bind.exec_driver_sql(f"DROP TABLE IF EXISTS {', '.join(_GALLERY_TABLES)}")


_GALLERY_DDL = (
    """
    CREATE TABLE galleries (
        deleted_at timestamp with time zone,
        deleted_by integer,
        purge_at timestamp with time zone,
        comments_enabled boolean DEFAULT true NOT NULL,
        id serial NOT NULL,
        initiative_id integer NOT NULL,
        name character varying(255) NOT NULL,
        description text,
        cover_image_id integer,
        created_by integer,
        created_at timestamp with time zone NOT NULL,
        updated_at timestamp with time zone NOT NULL,
        archived_at timestamp with time zone,
        listing_uid character varying(14),
        listing_version character varying(32),
        held_at timestamp with time zone,
        hold_id integer,
        comments_locked_at timestamp with time zone,
        CONSTRAINT galleries_pkey PRIMARY KEY (id),
        CONSTRAINT galleries_initiative_id_fkey FOREIGN KEY (initiative_id)
            REFERENCES initiatives(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_galleries_initiative_id ON galleries (initiative_id)",
    "CREATE INDEX ix_galleries_purge ON galleries (purge_at) "
    "WHERE purge_at IS NOT NULL",
    """
    CREATE TABLE gallery_images (
        deleted_at timestamp with time zone,
        deleted_by integer,
        purge_at timestamp with time zone,
        id serial NOT NULL,
        gallery_id integer NOT NULL,
        title character varying(255),
        caption text,
        created_by integer,
        created_at timestamp with time zone NOT NULL,
        updated_at timestamp with time zone NOT NULL,
        current_version_id integer,
        held_at timestamp with time zone,
        hold_id integer,
        CONSTRAINT gallery_images_pkey PRIMARY KEY (id),
        CONSTRAINT gallery_images_gallery_id_fkey FOREIGN KEY (gallery_id)
            REFERENCES galleries(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_gallery_images_created_at ON gallery_images (created_at)",
    "CREATE INDEX ix_gallery_images_current_version_id "
    "ON gallery_images (current_version_id)",
    "CREATE INDEX ix_gallery_images_gallery_id ON gallery_images (gallery_id)",
    "CREATE INDEX ix_gallery_images_purge ON gallery_images (purge_at) "
    "WHERE purge_at IS NOT NULL",
    """
    CREATE TABLE gallery_image_versions (
        id serial NOT NULL,
        gallery_image_id integer NOT NULL,
        version_number integer NOT NULL,
        file_url character varying(512) NOT NULL,
        thumbnail_url character varying(512),
        file_content_type character varying(128) NOT NULL,
        file_size bigint,
        original_filename character varying(255),
        width integer,
        height integer,
        created_by integer,
        created_at timestamp with time zone NOT NULL,
        CONSTRAINT gallery_image_versions_pkey PRIMARY KEY (id),
        CONSTRAINT uq_giv_image_version UNIQUE (gallery_image_id, version_number),
        CONSTRAINT gallery_image_versions_gallery_image_id_fkey
            FOREIGN KEY (gallery_image_id) REFERENCES gallery_images(id)
            ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_gallery_image_versions_gallery_image_id "
    "ON gallery_image_versions (gallery_image_id)",
    "ALTER TABLE galleries ADD CONSTRAINT galleries_cover_image_id_fkey "
    "FOREIGN KEY (cover_image_id) REFERENCES gallery_images(id) ON DELETE SET NULL",
    "ALTER TABLE gallery_images ADD CONSTRAINT gallery_images_current_version_id_fkey "
    "FOREIGN KEY (current_version_id) REFERENCES gallery_image_versions(id)",
    "CREATE TRIGGER tr_galleries_install_owns AFTER INSERT ON galleries "
    "FOR EACH ROW EXECUTE FUNCTION public.fn_install_owns_what_it_creates('gallery')",
    "ALTER TABLE comments ADD COLUMN gallery_id integer",
    "ALTER TABLE comments ADD CONSTRAINT comments_gallery_id_fkey "
    "FOREIGN KEY (gallery_id) REFERENCES galleries(id) ON DELETE CASCADE",
    "CREATE INDEX ix_comments_gallery_id ON comments (gallery_id)",
    "ALTER TABLE initiatives ADD COLUMN galleries_enabled boolean "
    "DEFAULT false NOT NULL",
)
#: A community's schema keeps its tables' row security; the template has none.
_GALLERY_RLS = tuple(
    statement
    for table in _GALLERY_TABLES
    for statement in (
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
    )
)


# --- the conversion ----------------------------------------------------------


def _create_map(bind: Connection) -> None:
    bind.exec_driver_sql(
        f"CREATE TEMP TABLE IF NOT EXISTS {_MAP} ("
        "schema_name text NOT NULL, image_id integer NOT NULL, "
        "file_id integer NOT NULL, gallery_id integer NOT NULL, "
        "initiative_id integer NOT NULL, person integer, "
        "PRIMARY KEY (schema_name, image_id)) ON COMMIT DROP"
    )


def _map_pictures(bind: Connection) -> None:
    """Give each picture that has a version its file's id, and name the person
    its rows are written for: its author, else its gallery's, else the
    gallery's owner (or the member who installed the plug-in that owns it)."""
    _create_map(bind)
    bind.exec_driver_sql(f"DELETE FROM {_MAP} m WHERE {_IN_SCHEMA}")
    bind.exec_driver_sql(
        f"INSERT INTO {_MAP} (schema_name, image_id, file_id, gallery_id, "
        "initiative_id, person) "
        "SELECT current_schema(), i.id, "
        "nextval(pg_get_serial_sequence('files', 'id')), g.id, g.initiative_id, "
        "coalesce(i.created_by, g.created_by, o.user_id, o.installer) "
        "FROM gallery_images i JOIN galleries g ON g.id = i.gallery_id "
        "LEFT JOIN LATERAL (SELECT r.user_id, p.created_by AS installer "
        "FROM resource_grants r LEFT JOIN guild_plugins p ON p.id = r.plugin_install_id "
        "WHERE r.resource_type = 'gallery' AND r.resource_id = g.id "
        "AND r.level = 'owner' LIMIT 1) o ON true "
        "WHERE EXISTS (SELECT 1 FROM gallery_image_versions v "
        "WHERE v.gallery_image_id = i.id) "
        "ORDER BY i.id"
    )


def _collections(bind: Connection) -> None:
    kept = set(_columns(bind, "collections")) - {"cover_image_id"}
    columns = [c for c in _columns(bind, "galleries") if c in kept]
    names = ", ".join(columns)
    bind.exec_driver_sql(
        f"INSERT INTO collections ({names}) SELECT {names} FROM galleries"
    )
    bind.exec_driver_sql(
        "SELECT setval(pg_get_serial_sequence('collections', 'id'), max(id)) "
        "FROM collections HAVING max(id) IS NOT NULL"
    )


def _files(bind: Connection) -> None:
    media = "lower(trim(split_part(v.file_content_type, ';', 1)))"
    bind.exec_driver_sql(
        "INSERT INTO files (id, initiative_id, is_template, name, file_type, "
        "created_by, created_at, updated_at, deleted_at, deleted_by, purge_at, "
        "held_at, hold_id) "
        "SELECT m.file_id, m.initiative_id, false, "
        "left(coalesce(nullif(btrim(i.title), ''), "
        "nullif(btrim(v.original_filename), ''), "
        "nullif(regexp_replace(v.file_url, '^.*/', ''), ''), v.file_url), 255), "
        f"{_case(media, _PICTURE_FORMATS, 'other')}, "
        "i.created_by, i.created_at, i.updated_at, "
        "coalesce(i.deleted_at, g.deleted_at), "
        "CASE WHEN i.deleted_at IS NOT NULL THEN i.deleted_by ELSE g.deleted_by END, "
        "coalesce(i.purge_at, g.purge_at), coalesce(i.held_at, g.held_at), "
        "CASE WHEN i.held_at IS NOT NULL THEN i.hold_id ELSE g.hold_id END "
        f"FROM {_MAP} m JOIN gallery_images i ON i.id = m.image_id "
        "JOIN galleries g ON g.id = i.gallery_id "
        "CROSS JOIN LATERAL (SELECT * FROM gallery_image_versions v "
        "WHERE v.gallery_image_id = i.id "
        "ORDER BY v.id = i.current_version_id DESC, v.version_number DESC "
        f"LIMIT 1) v WHERE {_IN_SCHEMA}"
    )
    bind.exec_driver_sql(
        "INSERT INTO file_versions (file_id, version_number, file_url, "
        "file_content_type, file_size, original_filename, width, height, "
        "created_by, created_at, thumbnail_state) "
        "SELECT m.file_id, v.version_number, v.file_url, v.file_content_type, "
        "v.file_size, v.original_filename, v.width, v.height, "
        "coalesce(v.created_by, m.person), v.created_at, "
        "CASE WHEN lower(trim(split_part(v.file_content_type, ';', 1))) "
        f"IN ({_THUMBNAILED}) THEN 'pending' END "
        f"FROM gallery_image_versions v JOIN {_MAP} m "
        f"ON m.image_id = v.gallery_image_id WHERE {_IN_SCHEMA}"
    )
    bind.exec_driver_sql(
        "UPDATE files f SET current_version_id = ("
        "SELECT fv.id FROM file_versions fv "
        "JOIN gallery_images i ON i.id = m.image_id "
        "LEFT JOIN gallery_image_versions gv ON gv.id = i.current_version_id "
        "WHERE fv.file_id = f.id "
        "ORDER BY fv.version_number = gv.version_number DESC, "
        "fv.version_number DESC LIMIT 1) "
        f"FROM {_MAP} m WHERE {_IN_SCHEMA} AND f.id = m.file_id"
    )


def _membership_and_cover(bind: Connection) -> None:
    bind.exec_driver_sql(
        "INSERT INTO collection_files (collection_id, file_id, initiative_id, "
        "added_by, added_at) "
        "SELECT m.gallery_id, m.file_id, m.initiative_id, m.person, i.created_at "
        f"FROM {_MAP} m JOIN gallery_images i ON i.id = m.image_id WHERE {_IN_SCHEMA}"
    )
    bind.exec_driver_sql(
        "UPDATE collections c SET cover_file_id = m.file_id "
        f"FROM galleries g JOIN {_MAP} m ON m.image_id = g.cover_image_id "
        f"AND {_IN_SCHEMA} WHERE c.id = g.id"
    )


def _copy_grants(bind: Connection, table: str) -> None:
    """Each of a gallery's rows in ``table``, once per picture's file."""
    if not _table_exists(bind, table):
        return
    columns = [
        c
        for c in _columns(bind, table)
        if c not in ("id", "resource_type", "resource_id")
    ]
    names = ", ".join(columns)
    picked = ", ".join(f"r.{c}" for c in columns)
    bind.exec_driver_sql(
        f"INSERT INTO {table} ({names}, resource_type, resource_id) "
        f"SELECT {picked}, 'file', m.file_id FROM {table} r "
        f"JOIN {_MAP} m ON m.gallery_id = r.resource_id AND {_IN_SCHEMA} "
        "WHERE r.resource_type = 'gallery'"
    )
    bind.exec_driver_sql(
        f"DELETE FROM {table} WHERE resource_type IN ('{_GALLERY}', '{_PICTURE}')"
    )


def _retarget(bind: Connection, table: str, kind: str, row_id: str) -> None:
    """A picture's rows name its file, a gallery's its collection."""
    bind.exec_driver_sql(
        f"UPDATE {table} t SET {kind} = 'file', {row_id} = m.file_id FROM {_MAP} m "
        f"WHERE {_IN_SCHEMA} AND t.{kind} = '{_PICTURE}' AND t.{row_id} = m.image_id"
    )
    bind.exec_driver_sql(f"DELETE FROM {table} WHERE {kind} = '{_PICTURE}'")
    bind.exec_driver_sql(
        f"UPDATE {table} SET {kind} = '{_COLLECTION}' WHERE {kind} = '{_GALLERY}'"
    )


def _retarget_all(bind: Connection) -> None:
    for table, kind, row_id in _NAMED_BY_KIND:
        _retarget(bind, table, kind, row_id)
    symmetric = ", ".join(f"'{t}'" for t in _SYMMETRIC_TYPES)
    bind.exec_driver_sql(
        "UPDATE relationships SET source_type = target_type, "
        "source_id = target_id, target_type = source_type, target_id = source_id "
        f"WHERE relationship_type IN ({symmetric}) AND source_node > target_node"
    )
    bookmarked = f"entity_type = '{_COLLECTION}' AND bookmarked_at IS NOT NULL"
    bind.exec_driver_sql(
        f"DELETE FROM personal_items WHERE {bookmarked} AND num_nonnulls("
        "viewed_at, subscribed_at, unsubscribed_at, sort_order) = 0"
    )
    bind.exec_driver_sql(
        f"UPDATE personal_items SET bookmarked_at = NULL WHERE {bookmarked}"
    )
    # A picture's entry is its file's, and decided by it.
    bind.exec_driver_sql(
        "UPDATE search_entries t SET entity_type = 'file', entity_id = m.file_id, "
        f"dac_tool = 'file', dac_id = m.file_id FROM {_MAP} m WHERE {_IN_SCHEMA} "
        f"AND t.entity_type = '{_PICTURE}' AND t.entity_id = m.image_id"
    )
    _retarget(bind, "search_entries", "entity_type", "entity_id")
    _retarget(bind, "search_entries", "dac_tool", "dac_id")
    bind.exec_driver_sql(
        "UPDATE reaction_digest_items t SET target_type = 'file', "
        "target_id = m.file_id, target_path = '/go/file/' || m.file_id "
        f"FROM {_MAP} m WHERE {_IN_SCHEMA} AND t.target_type = '{_PICTURE}' "
        "AND t.target_id = m.image_id"
    )
    bind.exec_driver_sql(
        f"DELETE FROM reaction_digest_items WHERE target_type = '{_PICTURE}'"
    )
    bind.exec_driver_sql(
        f"UPDATE reaction_digest_items SET target_type = '{_COLLECTION}', "
        f"target_path = '/go/{_COLLECTION}/' || target_id "
        f"WHERE target_type = '{_GALLERY}'"
    )
    bind.exec_driver_sql(
        f"DELETE FROM plugin_metadata WHERE entity_type = '{_PICTURE}'"
    )
    bind.exec_driver_sql(
        "UPDATE comments SET collection_id = gallery_id, gallery_id = NULL "
        "WHERE gallery_id IS NOT NULL"
    )


def _layouts(bind: Connection) -> None:
    bind.exec_driver_sql(
        f"DELETE FROM tool_layouts WHERE tool = '{_GALLERY}' OR kind = '{_PICTURE}'"
    )
    rows = ", ".join(
        f"('{kind}', '{json.dumps(body)}')" for kind, body in _COLLECTION_LAYOUTS
    )
    bind.exec_driver_sql(
        "INSERT INTO tool_layouts (initiative_id, tool, tool_id, kind, definition, "
        "created_at, updated_at) "
        f"SELECT g.initiative_id, '{_COLLECTION}', g.id, l.kind, "
        "CAST(l.definition AS jsonb), now(), now() "
        f"FROM galleries g CROSS JOIN (VALUES {rows}) AS l(kind, definition)"
    )


def _without_galleries(value: Any) -> Any:
    """An install's definition with no gallery scope, event type or entry
    naming a gallery kind."""

    def names_gallery(item: Any) -> bool:
        if isinstance(item, str):
            return (
                item in _SCOPES
                or item in (_GALLERY, _PICTURE)
                or item.startswith(_EVENT_PREFIX)
            )
        if isinstance(item, dict):
            return any(item.get(key) in (_GALLERY, _PICTURE) for key in _KIND_KEYS)
        return False

    if isinstance(value, list):
        return [_without_galleries(v) for v in value if not names_gallery(v)]
    if isinstance(value, dict):
        return {k: _without_galleries(v) for k, v in value.items() if k not in _SCOPES}
    return value


def _array_without(bind: Connection, table: str, column: str, where: str) -> None:
    """Remove from a text array every element ``where`` holds of ``v``."""
    bind.exec_driver_sql(
        f"UPDATE {table} SET {column} = ARRAY(SELECT v FROM unnest({column}) "
        f"WITH ORDINALITY AS u(v, i) WHERE NOT ({where}) ORDER BY i) "
        f"WHERE EXISTS (SELECT 1 FROM unnest({column}) v WHERE {where})"
    )


def _settle_plugins_and_hooks(bind: Connection) -> None:
    scopes = ", ".join(f"'{s}'" for s in _SCOPES)
    _array_without(bind, "guild_plugins", "granted_scopes", f"v IN ({scopes})")
    rows = bind.execute(
        text(
            "SELECT id, definition FROM guild_plugins WHERE CAST(definition AS text) ~ 'galler'"
        )
    ).all()
    for row_id, definition in rows:
        if isinstance(definition, str):
            definition = json.loads(definition)
        cleaned = _without_galleries(definition)
        if cleaned != definition:
            bind.execute(
                text(
                    "UPDATE guild_plugins SET definition = CAST(:d AS jsonb) WHERE id = :id"
                ),
                {"d": json.dumps(cleaned), "id": row_id},
            )
    gallery_event = f"starts_with(CAST(v AS text), '{_EVENT_PREFIX}')"
    _array_without(bind, "webhook_subscriptions", "event_types", gallery_event)
    fields = ", ".join(f"'{f}'" for f in _GALLERY_FIELDS)
    _array_without(
        bind,
        "webhook_subscriptions",
        "fields",
        f"CAST(v AS text) IN ({fields})",
    )
    empty = "cardinality(event_types) = 0"
    bind.exec_driver_sql(
        "DELETE FROM webhook_deliveries WHERE subscription_id IN "
        f"(SELECT id FROM webhook_subscriptions WHERE {empty})"
    )
    bind.exec_driver_sql(f"DELETE FROM webhook_subscriptions WHERE {empty}")


def _forget(bind: Connection) -> None:
    """What only the gallery tool had."""
    permissions = ", ".join(f"'{p}'" for p in _PERMISSIONS)
    resources = ", ".join(f"'{r}'" for r in _RESOURCES)
    bind.exec_driver_sql(
        f"DELETE FROM initiative_role_permissions WHERE permission_key IN ({permissions})"
    )
    bind.exec_driver_sql(
        f"DELETE FROM event_outbox WHERE resource_type IN ({resources}) "
        f"OR dac_tool IN ('{_GALLERY}', '{_PICTURE}') "
        "OR (jsonb_typeof(parents) = 'array' AND EXISTS (SELECT 1 FROM "
        f"jsonb_array_elements(parents) p WHERE p ->> 'type' IN ({resources})))"
    )
    bind.exec_driver_sql(
        f"DELETE FROM plugin_event_outbox WHERE starts_with(event_type, '{_EVENT_PREFIX}')"
    )
    bind.exec_driver_sql(
        f"DELETE FROM export_jobs WHERE source = '{_GALLERY}' "
        "AND status IN ('queued', 'running')"
    )
    bind.exec_driver_sql(
        "DELETE FROM import_jobs WHERE source = 'initiative-gallery' "
        "AND status IN ('staged', 'fetching', 'queued', 'running')"
    )


# --- links in stored content ----------------------------------------------

#: Bodies an editor session edits, each with a Yjs state beside its JSON, and
#: which of their rows hold a Lexical body.
_LIVE_BODIES = (("files", "file_type = 'lexical'"), ("wiki_pages", "true"))
#: Lexical bodies with no Yjs state.
_STATE_BODIES = (("posts", "body"),)
#: Markdown: a text column, or every string in a JSON one.
_MARKDOWN = (
    ("initiatives", "description"),
    ("projects", "description"),
    ("queues", "description"),
    ("counter_groups", "description"),
    ("calendars", "description"),
    ("dashboards", "description"),
    ("wikis", "description"),
    ("collections", "description"),
    ("tasks", "description"),
    ("tasks", "checklist"),
    ("tasks", "recurrence_carry"),
    ("task_types", "starting_values"),
    ("queue_items", "notes"),
    ("calendar_events", "description"),
    ("calendar_events", "location"),
    ("comments", "content"),
)
_LINK_TABLES = tuple(
    dict.fromkeys(t for t, *_ in (*_LIVE_BODIES, *_STATE_BODIES, *_MARKDOWN))
)
#: An old spelling in a Lexical body's JSON, and in running text.
_OLD_IN_STATE = r'"(wikilink|document|gallery|gallery_image)[":]'
_OLD_IN_TEXT = r"#(doc|document|gallery)"
#: An old spelling in a Yjs state: a ``wikilink`` node, a kind or chip that
#: says ``document``, or anything that says ``gallery``. The node type and a
#: kind are each stored as a whole string value, its length before it.
_OLD_IN_YJS = (b"wikilink", b"\x77\x08document", b"document:", b"gallery")
#: The style a ``wikilink`` is read under while it is a plain text node, with
#: its place among the document's wikilinks after it.
_WIKILINK_MARK = "initiative-wikilink:"


def _retype_wikilinks(doc: Doc) -> list[dict[str, Any]]:
    """Each ``wikilink`` node in a Yjs state made a text node carrying its
    place in ``_WIKILINK_MARK``, for an editor that reads no ``wikilink``; and
    what each one named, in that order."""
    found: list[dict[str, Any]] = []

    def walk(shared: Any) -> None:
        for raw, _attrs in shared.diff():
            child = shared._maybe_as_type_or_doc(raw)
            if isinstance(child, (Text, XmlText)):
                walk(child)
            elif isinstance(child, Map) and child.get("__type") == "wikilink":
                found.append(
                    {
                        "documentId": child.get("__documentId"),
                        "documentTitle": child.get("__documentTitle"),
                    }
                )
                with doc.transaction():
                    child["__type"] = "text"
                    child["__style"] = f"{_WIKILINK_MARK}{len(found) - 1}"
                    for key in ("__documentId", "__documentTitle"):
                        if key in child:
                            del child[key]

    walk(doc.get("root", type=Text))
    return found


def _whole(value: Any) -> Any:
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _with_wikilinks(content: Any, found: list[dict[str, Any]]) -> Any:
    """The editor's reading with each marked text node its ``wikilink`` again."""
    if isinstance(content, list):
        return [_with_wikilinks(item, found) for item in content]
    if not isinstance(content, dict):
        return content
    style = content.get("style")
    if content.get("type") == "text" and isinstance(style, str):
        place = style.removeprefix(_WIKILINK_MARK)
        if place != style and place.isdecimal() and int(place) < len(found):
            link = found[int(place)]
            return {
                "type": "wikilink",
                "version": 1,
                "text": content.get("text", ""),
                "documentId": _whole(link["documentId"]),
                "documentTitle": link["documentTitle"],
            }
    return {key: _with_wikilinks(item, found) for key, item in content.items()}


def _nameless(value: Any) -> Any:
    """A Lexical body as it is stored: a mention of somebody by id carries no
    name."""
    if isinstance(value, list):
        return [_nameless(item) for item in value]
    if not isinstance(value, dict):
        return value
    out = {key: _nameless(item) for key, item in value.items()}
    if out.get("mentionUserId") is None:
        return out
    return {**out, "mentionName": "", "text": ""}


def _rewrite_live(state: bytes, files: Mapping[int, int]) -> tuple[Any, bytes] | None:
    """A body's JSON and Yjs state with its links rewritten, read and written
    through the editor; ``None`` when its state says nothing to rewrite.
    Raises :class:`editor_engine.EditorError` for a state the editor refuses."""
    doc = Doc()
    doc.apply_update(state)
    found = _retype_wikilinks(doc)
    readable = bytes(doc.get_update()) if found else state
    reading = await_only(editor_engine.render(readable))
    rewritten = rewrite_body(_with_wikilinks(reading, found), files)
    if not found and rewritten == reading:
        return None
    update = await_only(editor_engine.apply(readable, rewritten))
    doc.apply_update(update)
    return _nameless(rewritten), bytes(doc.get_update())


def _is_json(bind: Connection, table: str, column: str) -> bool:
    return (
        bind.execute(
            text(
                "SELECT format_type(atttypid, atttypmod) IN ('json', 'jsonb') "
                "FROM pg_attribute WHERE attrelid = to_regclass(:t) AND attname = :c"
            ),
            {"t": table, "c": column},
        ).scalar()
        is True
    )


def _strings(value: Any, files: Mapping[int, int]) -> Any:
    if isinstance(value, str):
        return rewrite_text(value, files)
    if isinstance(value, list):
        return [_strings(item, files) for item in value]
    if isinstance(value, dict):
        return {key: _strings(item, files) for key, item in value.items()}
    return value


def _write(
    bind: Connection,
    table: str,
    row_id: int,
    values: dict[str, Any],
    json_columns: set[str],
) -> None:
    sets = ", ".join(
        f"{column} = CAST(:{column} AS jsonb)"
        if column in json_columns
        else f"{column} = :{column}"
        for column in values
    )
    bind.execute(
        text(f"UPDATE {table} SET {sets} WHERE id = :row_id"),
        {
            **{
                column: json.dumps(value) if column in json_columns else value
                for column, value in values.items()
            },
            "row_id": row_id,
        },
    )


def _rewrite_links(bind: Connection) -> None:
    files = dict(
        bind.execute(
            text(f"SELECT image_id, file_id FROM {_MAP} m WHERE {_IN_SCHEMA}")
        ).all()
    )
    in_yjs = " OR ".join(
        f"position(CAST(:n{i} AS bytea) IN yjs_state) > 0"
        for i in range(len(_OLD_IN_YJS))
    )
    needles = {f"n{i}": needle for i, needle in enumerate(_OLD_IN_YJS)}
    editor_runs = False
    for table, lexical in _LIVE_BODIES:
        if not _table_exists(bind, table):
            continue
        rows = bind.execute(
            text(
                f"SELECT id, content, yjs_state FROM {table} WHERE {lexical} AND "
                f"((yjs_state IS NOT NULL AND ({in_yjs})) "
                "OR CAST(content AS text) ~ :old)"
            ),
            {**needles, "old": _OLD_IN_STATE},
        ).all()
        for row_id, content, state in rows:
            content = _as_json(content)
            live = None
            if state is not None and any(n in bytes(state) for n in _OLD_IN_YJS):
                if not editor_runs:
                    # An editor that cannot start fails the revision here.
                    await_only(editor_engine.bootstrap(None))
                    editor_runs = True
                try:
                    live = _rewrite_live(bytes(state), files)
                except editor_engine.EditorError:
                    # A state the editor refuses opens nowhere: the body is its
                    # JSON, and the next session makes a state from it.
                    live = (rewrite_body(content, files), None)
            if live is not None:
                bind.execute(
                    text(
                        f"UPDATE {table} SET content = CAST(:c AS jsonb), "
                        "yjs_state = :s, yjs_updated_at = now() WHERE id = :id"
                    ),
                    {"c": json.dumps(live[0]), "s": live[1], "id": row_id},
                )
                continue
            rewritten = rewrite_body(content, files)
            if rewritten != content:
                _write(bind, table, row_id, {"content": rewritten}, {"content"})
    for table, column in _STATE_BODIES:
        if not _table_exists(bind, table):
            continue
        rows = bind.execute(
            text(
                f"SELECT id, {column} FROM {table} WHERE CAST({column} AS text) ~ :old"
            ),
            {"old": _OLD_IN_STATE},
        ).all()
        for row_id, body in rows:
            body = _as_json(body)
            rewritten = rewrite_body(body, files)
            if rewritten != body:
                _write(bind, table, row_id, {column: rewritten}, {column})
    for table, column in _MARKDOWN:
        if not _table_exists(bind, table):
            continue
        json_columns = {column} if _is_json(bind, table, column) else set()
        rows = bind.execute(
            text(
                f"SELECT id, {column} FROM {table} WHERE CAST({column} AS text) ~ :old"
            ),
            {"old": _OLD_IN_TEXT},
        ).all()
        for row_id, value in rows:
            value = _as_json(value) if json_columns else value
            rewritten = _strings(value, files)
            if rewritten != value:
                _write(bind, table, row_id, {column: rewritten}, json_columns)


def _upgrade_schema(bind: Connection) -> None:
    checks = _drop_checks(bind, _GALLERY_CHECK, (_SYMMETRIC_CHECK,))
    if _table_exists(bind, "galleries"):
        with _held(bind, _TOUCHED):
            _map_pictures(bind)
            _collections(bind)
            _files(bind)
            _membership_and_cover(bind)
            _copy_grants(bind, "resource_grants")
            _copy_grants(bind, "guest_invite_grants")
            _retarget_all(bind)
            _layouts(bind)
            _settle_plugins_and_hooks(bind)
            _forget(bind)
            _drop_gallery_structure(bind)
    with _held(bind, _LINK_TABLES):
        _rewrite_links(bind)
    _restore_checks(bind, checks, _forward_check)
    bind.exec_driver_sql(_CLEAR_SEARCH_GENERATION)


def _downgrade_schema(bind: Connection) -> None:
    checks = _drop_checks(bind, _COLLECTION_CHECK, (_PERMISSION_CHECK, _METADATA_CHECK))
    if not _table_exists(bind, "galleries"):
        with _held(bind, _TOUCHED):
            for table, kind, _row_id in _NAMED_BY_KIND:
                bind.exec_driver_sql(
                    f"DELETE FROM {table} WHERE {kind} = '{_COLLECTION}'"
                )
            bind.exec_driver_sql(
                f"DELETE FROM search_entries WHERE entity_type = '{_COLLECTION}' "
                f"OR dac_tool = '{_COLLECTION}'"
            )
            for table, kind in (
                ("reaction_digest_items", "target_type"),
                ("plugin_metadata", "entity_type"),
                ("tool_layouts", "tool"),
            ):
                bind.exec_driver_sql(
                    f"DELETE FROM {table} WHERE {kind} = '{_COLLECTION}'"
                )
            bind.exec_driver_sql(
                "DELETE FROM tool_layouts WHERE kind IN "
                f"({', '.join(repr(k) for k in _LIST_KINDS)})"
            )
            bind.exec_driver_sql("DELETE FROM comments WHERE collection_id IS NOT NULL")
            template = (
                bind.execute(text("SELECT current_schema()")).scalar()
                == "guild_template"
            )
            for statement in _GALLERY_DDL + (() if template else _GALLERY_RLS):
                bind.exec_driver_sql(statement)
    _restore_checks(bind, checks, _backward_check)
    bind.exec_driver_sql(_CLEAR_SEARCH_GENERATION)


def _apply(forward: bool) -> None:
    """One guild schema, the one the search_path names."""
    bind = op.get_bind()
    (_upgrade_schema if forward else _downgrade_schema)(bind)


# --- public ------------------------------------------------------------------


class _Unmapped(Exception):
    """A picture with no file."""


_GO = re.compile(r"(/|%2F)go\1(gallery_image|gallery)\1(\d+)")
_PAGE = re.compile(r"(/|%2F)c\1\d+\1i\1\d+\1galleries\1(\d+)")
_ROLLUP = re.compile(r"(^|:)(gallery_image|gallery):(\d+)(?=:|$)")
#: (kind key, id key) pairs a notice's data carries.
_DATA_KINDS = (
    ("entity_type", "entity_id"),
    ("subject_type", "subject_id"),
    ("context_entity_type", "context_entity_id"),
)


def _notice_respeller(files: Mapping[int, int]) -> dict[str, Callable[..., Any]]:
    """How each part of a notice reads with its picture a file and its gallery
    a collection. Raises :class:`_Unmapped` for a picture with no file."""

    def file_of(value: Any) -> int:
        try:
            return files[int(value)]
        except (KeyError, TypeError, ValueError):
            raise _Unmapped from None

    def kind(old: str, value: Any) -> tuple[str, Any]:
        if old == _PICTURE:
            return "file", None if value is None else file_of(value)
        return _COLLECTION, value

    def address(value: str) -> str:
        def go(m: re.Match[str]) -> str:
            sep, old, number = m.group(1), m.group(2), m.group(3)
            new, ident = kind(old, number)
            return f"{sep}go{sep}{new}{sep}{ident}"

        value = _GO.sub(go, value)
        return _PAGE.sub(
            lambda m: (
                f"{m.group(1)}go{m.group(1)}{_COLLECTION}{m.group(1)}{m.group(2)}"
            ),
            value,
        )

    def rollup(value: str) -> str:
        def one(m: re.Match[str]) -> str:
            new, ident = kind(m.group(2), m.group(3))
            return f"{m.group(1)}{new}:{ident}"

        return _ROLLUP.sub(one, value)

    def data(value: Any) -> Any:
        if isinstance(value, list):
            return [data(item) for item in value]
        if isinstance(value, str):
            return address(value)
        if not isinstance(value, dict):
            return value
        out = dict(value)
        picture_file = None
        for kind_key, id_key in _DATA_KINDS:
            if out.get(kind_key) in (_GALLERY, _PICTURE):
                out[kind_key], ident = kind(out[kind_key], out.get(id_key))
                if id_key in out:
                    out[id_key] = ident
                if out[kind_key] == "file":
                    picture_file = ident
        if out.get("tool") == _GALLERY:
            out["tool"] = "file"
            for key in ("tool_id", "resource_id"):
                if key in out:
                    out[key] = picture_file
        return {
            key: rollup(item)
            if key == "rollup_key" and isinstance(item, str)
            else item
            if key in ("tool", *(k for pair in _DATA_KINDS for k in pair))
            else data(item)
            for key, item in out.items()
        }

    return {"address": address, "rollup": rollup, "data": data, "kind": kind}


def _picture_files(bind: Connection) -> dict[int | None, dict[int, int]]:
    """The map, by community."""
    found: dict[int | None, dict[int, int]] = {}
    for schema, image, file in bind.execute(
        text(f"SELECT schema_name, image_id, file_id FROM {_MAP}")
    ).all():
        guild = (
            int(schema.removeprefix("guild_")) if schema != "guild_template" else None
        )
        found.setdefault(guild, {})[image] = file
    return found


def _as_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _notifications(bind: Connection, files: dict[int | None, dict[int, int]]) -> None:
    rows = bind.execute(
        text(
            "SELECT id, guild_id, tool, resource_id, subject_type, subject_id, data "
            "FROM public.notifications WHERE tool = :g OR subject_type IN (:g, :p) "
            "OR CAST(data AS text) ~ 'galler'"
        ),
        {"g": _GALLERY, "p": _PICTURE},
    ).all()
    for row_id, guild, tool, resource, subject_type, subject_id, payload in rows:
        respell = _notice_respeller(files.get(guild, {}))
        try:
            if subject_type in (_GALLERY, _PICTURE):
                subject_type, subject_id = respell["kind"](subject_type, subject_id)
            if tool == _GALLERY:
                tool = "file"
                resource = subject_id if subject_type == "file" else None
            payload = respell["data"](_as_json(payload))
        except _Unmapped:
            bind.execute(
                text("DELETE FROM public.notifications WHERE id = :id"), {"id": row_id}
            )
            continue
        bind.execute(
            text(
                "UPDATE public.notifications SET tool = :tool, resource_id = :resource, "
                "subject_type = :subject_type, subject_id = :subject_id, "
                "data = CAST(:data AS json) WHERE id = :id"
            ),
            {
                "tool": tool,
                "resource": resource,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "data": json.dumps(payload),
                "id": row_id,
            },
        )


def _notice_outbox(bind: Connection, files: dict[int | None, dict[int, int]]) -> None:
    rows = bind.execute(
        text(
            "SELECT id, guild_id, data, push_data, rollup_key, email_link "
            "FROM public.notice_outbox WHERE CAST(data AS text) ~ 'galler' "
            "OR CAST(push_data AS text) ~ 'galler' OR rollup_key ~ 'galler' "
            "OR email_link ~ 'galler'"
        )
    ).all()
    for row_id, guild, payload, push, rollup_key, link in rows:
        respell = _notice_respeller(files.get(guild, {}))
        try:
            payload = respell["data"](_as_json(payload))
            push = respell["data"](_as_json(push))
            rollup_key = None if rollup_key is None else respell["rollup"](rollup_key)
            link = None if link is None else respell["address"](link)
        except _Unmapped:
            bind.execute(
                text("DELETE FROM public.notice_outbox WHERE id = :id"), {"id": row_id}
            )
            continue
        bind.execute(
            text(
                "UPDATE public.notice_outbox SET data = CAST(:data AS jsonb), "
                "push_data = CAST(:push AS jsonb), rollup_key = :rollup, "
                "email_link = :link WHERE id = :id"
            ),
            {
                "data": json.dumps(payload),
                "push": None if push is None else json.dumps(push),
                "rollup": rollup_key,
                "link": link,
                "id": row_id,
            },
        )


def _public(bind: Connection) -> None:
    files = _picture_files(bind)
    tables = (
        "public.notifications",
        "public.notice_outbox",
        "public.plugin_service_registrations",
        "public.marketplace_listings",
        "public.marketplace_listing_versions",
        "public.user_view_preferences",
    )
    with _held(bind, tables):
        _notifications(bind, files)
        _notice_outbox(bind, files)
        scopes = ", ".join(f"'{s}'" for s in _SCOPES)
        _array_without(
            bind,
            "public.plugin_service_registrations",
            "scope_ceiling",
            f"CAST(v AS text) IN ({scopes})",
        )
        bind.exec_driver_sql(
            f"DELETE FROM public.marketplace_listings WHERE kind = '{_GALLERY}'"
        )
        bind.exec_driver_sql(
            f"DELETE FROM public.user_view_preferences WHERE {_VIEW_PREFERENCES}"
        )


# --- entry points ------------------------------------------------------------


def _convert(
    bind: Connection,
    forward: bool,
    each_schema: Callable[[Callable[[], None]], None],
) -> None:
    """Run ``_apply`` through ``each_schema`` with the kind code reading every
    kind either way, then, upgrading, the public half and the code reading
    only the kinds the rows now say."""
    bind.exec_driver_sql(_kind_code_fn(_KIND_CODES_EITHER))
    if forward:
        _create_map(bind)
    each_schema(lambda: _apply(forward))
    if forward:
        _public(bind)
        bind.exec_driver_sql(f"DROP TABLE IF EXISTS {_MAP}")
        bind.exec_driver_sql(_kind_code_fn(_KIND_CODES_AFTER))


def upgrade() -> None:
    bind = op.get_bind()
    _convert(bind, True, lambda apply: run_for_each_guild_schema(bind, apply))


def downgrade() -> None:
    bind = op.get_bind()
    _convert(bind, False, lambda apply: run_for_each_guild_schema(bind, apply))
