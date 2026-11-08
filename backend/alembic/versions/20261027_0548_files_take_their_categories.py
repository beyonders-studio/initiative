"""Files take their categories' formats

A file's type names more formats, so that a design file, a 3D model, a font,
a camera's raw picture, source code, an e-book or a drawing from a CAD program
shows as what it is rather than as ``other`` or the format its bytes borrow
(a PDF, a zip, plain text, a TIFF). In ``guild_template`` and every
``guild_<id>``:

* **Versions** — a version whose filename names one of these formats, and whose
  stored media type is one that format's bytes may read as, takes the format's
  media type: an Illustrator file stored as ``application/pdf`` is
  ``application/illustrator``.
* **Files** — a file whose current version's media type is one of these
  formats' takes that format as its type, as an upload of it would now.

Nothing about the bytes or the blobs changes. The writes run with each
table's row security unforced and its user triggers held, both restored in the
same transaction.

The downgrade makes every one of these files ``other``, the type the release
before this gives a media type it does not name; the versions keep their media
types.

Revision ID: 20261027_0548
Revises: 20261027_0547
Create Date: 2026-10-27
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261027_0548"
down_revision = "20261027_0547"
branch_labels = None
depends_on = None


#: Each format this revision names: its type, its media types (the one a
#: version is stored as first), its extensions, and what its bytes may have
#: been stored as.
_FORMATS: tuple[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...] = (
    ("rar", ("application/vnd.rar", "application/x-rar"), (".rar",), ()),
    (
        "ai",
        ("application/illustrator",),
        (".ai",),
        ("application/pdf", "application/postscript"),
    ),
    ("psd", ("image/vnd.adobe.photoshop",), (".psd", ".psb"), ()),
    ("eps", ("application/postscript", "image/x-eps"), (".eps", ".ps"), ()),
    ("indd", ("application/x-indesign",), (".indd",), ("application/octet-stream",)),
    ("xcf", ("image/x-xcf",), (".xcf",), ()),
    ("kra", ("application/x-krita",), (".kra",), ("application/zip",)),
    ("procreate", ("application/x-procreate",), (".procreate",), ("application/zip",)),
    ("clip", ("application/x-clip-studio",), (".clip",), ("application/octet-stream",)),
    ("sketch", ("application/x-sketch",), (".sketch",), ("application/zip",)),
    ("fig", ("application/x-fig",), (".fig",), ("application/octet-stream",)),
    (
        "afdesign",
        ("application/x-afdesign",),
        (".afdesign",),
        ("application/octet-stream",),
    ),
    (
        "afphoto",
        ("application/x-afphoto",),
        (".afphoto",),
        ("application/octet-stream",),
    ),
    ("afpub", ("application/x-afpub",), (".afpub",), ("application/octet-stream",)),
    ("cdr", ("application/vnd.corel-draw",), (".cdr",), ()),
    ("blend", ("application/x-blender",), (".blend",), ("application/octet-stream",)),
    ("fbx", ("application/x-fbx",), (".fbx",), ("application/octet-stream",)),
    ("obj", ("model/obj",), (".obj",), ("text/plain",)),
    ("stl", ("model/stl",), (".stl",), ("text/plain", "application/octet-stream")),
    ("glb", ("model/gltf-binary",), (".glb",), ()),
    ("gltf", ("model/gltf+json",), (".gltf",), ("application/json",)),
    ("3mf", ("model/3mf",), (".3mf",), ("application/zip",)),
    ("usdz", ("model/vnd.usdz+zip",), (".usdz",), ("application/zip",)),
    ("ttf", ("font/ttf", "font/sfnt"), (".ttf",), ()),
    ("otf", ("font/otf", "application/vnd.ms-opentype"), (".otf",), ("font/sfnt",)),
    ("woff", ("font/woff",), (".woff",), ("application/octet-stream",)),
    ("woff2", ("font/woff2",), (".woff2",), ("application/octet-stream",)),
    ("dng", ("image/x-adobe-dng",), (".dng",), ("image/tiff",)),
    ("cr2", ("image/x-canon-cr2",), (".cr2",), ("image/tiff",)),
    ("cr3", ("image/x-canon-cr3",), (".cr3",), ("application/octet-stream",)),
    ("nef", ("image/x-nikon-nef",), (".nef",), ("image/tiff",)),
    ("arw", ("image/x-sony-arw",), (".arw",), ("image/tiff",)),
    ("raf", ("image/x-fuji-raf",), (".raf",), ()),
    ("orf", ("image/x-olympus-orf",), (".orf",), ()),
    ("py", ("text/x-python", "text/x-script.python"), (".py",), ("text/plain",)),
    (
        "js",
        ("text/javascript", "application/javascript"),
        (".js", ".mjs", ".cjs"),
        ("text/plain",),
    ),
    ("ts", ("text/x-typescript",), (".ts", ".tsx"), ("text/plain",)),
    ("css", ("text/css",), (".css",), ("text/plain",)),
    ("sql", ("application/sql",), (".sql",), ("text/plain",)),
    ("yaml", ("application/yaml", "text/yaml"), (".yaml", ".yml"), ("text/plain",)),
    ("xml", ("text/xml", "application/xml"), (".xml",), ("text/plain",)),
    ("toml", ("application/toml",), (".toml",), ("text/plain",)),
    ("c", ("text/x-c",), (".c", ".h"), ("text/plain",)),
    (
        "cpp",
        ("text/x-c++",),
        (".cpp", ".cc", ".cxx", ".hpp"),
        ("text/plain", "text/x-c", "text/x-c++"),
    ),
    ("cs", ("text/x-csharp",), (".cs",), ("text/plain", "text/x-c", "text/x-c++")),
    ("java", ("text/x-java",), (".java",), ("text/plain", "text/x-c", "text/x-c++")),
    ("go", ("text/x-go",), (".go",), ("text/plain", "text/x-c", "text/x-c++")),
    ("rs", ("text/x-rust",), (".rs",), ("text/plain", "text/x-c", "text/x-c++")),
    ("rb", ("text/x-ruby",), (".rb",), ("text/plain",)),
    ("php", ("text/x-php",), (".php",), ("text/plain",)),
    ("swift", ("text/x-swift",), (".swift",), ("text/plain", "text/x-c", "text/x-c++")),
    (
        "kt",
        ("text/x-kotlin",),
        (".kt", ".kts"),
        ("text/plain", "text/x-c", "text/x-c++"),
    ),
    ("epub", ("application/epub+zip",), (".epub",), ()),
    (
        "mobi",
        ("application/x-mobipocket-ebook",),
        (".mobi",),
        ("application/octet-stream",),
    ),
    ("dwg", ("image/vnd.dwg",), (".dwg",), ()),
    ("dxf", ("image/vnd.dxf", "application/x-dxf"), (".dxf",), ("text/plain",)),
    ("step", ("model/step",), (".step", ".stp"), ("text/plain",)),
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _writable(bind: Connection, table: str, statements: list[str]) -> None:
    """Run ``statements`` with ``table``'s row security unforced and its user
    triggers held, both restored either way."""
    forced = bool(
        bind.execute(
            text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    )
    if forced:
        bind.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    bind.exec_driver_sql(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    try:
        for statement in statements:
            bind.exec_driver_sql(statement)
    finally:
        bind.exec_driver_sql(f"ALTER TABLE {table} ENABLE TRIGGER USER")
        if forced:
            bind.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


_MEDIA = "lower(trim(split_part({}.file_content_type, ';', 1)))"


def _upgrade_schema(bind: Connection) -> None:
    versions = []
    for _type, media_types, extensions, containers in _FORMATS:
        if not containers:
            continue
        names = "|".join(extension.lstrip(".") for extension in extensions)
        versions.append(
            f"UPDATE file_versions v SET file_content_type = '{media_types[0]}' "
            f"WHERE {_MEDIA.format('v')} IN ({_quoted(containers)}) "
            f"AND lower(v.original_filename) ~ '\\.({names})$'"
        )
    _writable(bind, "file_versions", versions)
    arms = " ".join(
        f"WHEN {_MEDIA.format('v')} IN ({_quoted(media_types)}) THEN '{file_type}'"
        for file_type, media_types, _extensions, _containers in _FORMATS
    )
    every = _quoted(tuple(m for _t, media, _e, _c in _FORMATS for m in media))
    _writable(
        bind,
        "files",
        [
            f"UPDATE files f SET file_type = CASE {arms} END "
            "FROM file_versions v WHERE v.id = f.current_version_id "
            f"AND {_MEDIA.format('v')} IN ({every})"
        ],
    )


def _downgrade_schema(bind: Connection) -> None:
    named = _quoted(tuple(file_type for file_type, *_rest in _FORMATS))
    _writable(
        bind,
        "files",
        [f"UPDATE files SET file_type = 'other' WHERE file_type IN ({named})"],
    )


def upgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _upgrade_schema(bind))


def downgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _downgrade_schema(bind))
