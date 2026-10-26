"""What a file is: its type, and the kind that decides how it is shown.

A file's **type** is its format: the editor's own formats (``lexical``,
``excalidraw``, ``sheet``, ``url``) and the formats an upload can be (``pdf``,
``docx``, ``png`` …), with ``other`` for anything else. Its **kind** follows
from the type: a ``sheet``, an ``xlsx`` and a ``csv`` are all spreadsheets.

The type is what ``files.file_type`` stores. The kind is never stored; a
filter by kind reads :func:`types_of_kind`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class FileType(str, Enum):
    lexical = "lexical"
    excalidraw = "excalidraw"
    sheet = "sheet"
    url = "url"
    pdf = "pdf"
    doc = "doc"
    docx = "docx"
    xls = "xls"
    xlsx = "xlsx"
    ppt = "ppt"
    pptx = "pptx"
    txt = "txt"
    html = "html"
    md = "md"
    png = "png"
    jpeg = "jpeg"
    gif = "gif"
    webp = "webp"
    svg = "svg"
    other = "other"


class FileKind(str, Enum):
    document = "document"
    spreadsheet = "spreadsheet"
    presentation = "presentation"
    whiteboard = "whiteboard"
    pdf = "pdf"
    image = "image"
    video = "video"
    audio = "audio"
    text = "text"
    archive = "archive"
    link = "link"
    other = "other"


@dataclass(frozen=True)
class FileTypeSpec:
    kind: FileKind
    #: The media types a stored version of this type has, the canonical one
    #: first. Empty for the editor's own types, which have no stored version.
    media_types: tuple[str, ...] = ()
    #: For the editor's own types: what an export of one may be written as.
    #: Every other type exports as its stored file.
    exports: tuple[str, ...] = ()

    @property
    def stored(self) -> bool:
        """Whether a file of this type is stored versions rather than a body
        the editor keeps in the database."""
        return bool(self.media_types)


SPECS: dict[FileType, FileTypeSpec] = {
    FileType.lexical: FileTypeSpec(
        FileKind.document, exports=("json", "md", "pdf", "docx")
    ),
    FileType.excalidraw: FileTypeSpec(FileKind.whiteboard, exports=("json",)),
    FileType.sheet: FileTypeSpec(FileKind.spreadsheet, exports=("csv", "xlsx", "json")),
    FileType.url: FileTypeSpec(FileKind.link, exports=("md", "json")),
    FileType.pdf: FileTypeSpec(FileKind.pdf, ("application/pdf",)),
    FileType.doc: FileTypeSpec(FileKind.document, ("application/msword",)),
    FileType.docx: FileTypeSpec(
        FileKind.document,
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
    ),
    FileType.xls: FileTypeSpec(FileKind.spreadsheet, ("application/vnd.ms-excel",)),
    FileType.xlsx: FileTypeSpec(
        FileKind.spreadsheet,
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
    ),
    FileType.ppt: FileTypeSpec(
        FileKind.presentation, ("application/vnd.ms-powerpoint",)
    ),
    FileType.pptx: FileTypeSpec(
        FileKind.presentation,
        ("application/vnd.openxmlformats-officedocument.presentationml.presentation",),
    ),
    FileType.txt: FileTypeSpec(FileKind.text, ("text/plain",)),
    FileType.html: FileTypeSpec(FileKind.text, ("text/html",)),
    FileType.md: FileTypeSpec(FileKind.document, ("text/markdown", "text/x-markdown")),
    FileType.png: FileTypeSpec(FileKind.image, ("image/png",)),
    FileType.jpeg: FileTypeSpec(FileKind.image, ("image/jpeg", "image/jpg")),
    FileType.gif: FileTypeSpec(FileKind.image, ("image/gif",)),
    FileType.webp: FileTypeSpec(FileKind.image, ("image/webp",)),
    FileType.svg: FileTypeSpec(FileKind.image, ("image/svg+xml",)),
    FileType.other: FileTypeSpec(FileKind.other, ("application/octet-stream",)),
}

#: The types the editor creates and keeps as a body.
EDITOR_TYPES = tuple(t for t, spec in SPECS.items() if not spec.stored)

#: What the editor's types were called before they took their formats' names.
#: Backups and listings made then still say so.
_FORMER_NAMES = {
    "native": FileType.lexical,
    "whiteboard": FileType.excalidraw,
    "spreadsheet": FileType.sheet,
    "smart_link": FileType.url,
}

_BY_MEDIA_TYPE = {
    media: file_type for file_type, spec in SPECS.items() for media in spec.media_types
}


def type_named(name: Any) -> Any:
    """The type an envelope's ``file_type`` names, under either name it has
    had; anything else is returned as it is, for its reader to refuse."""
    former = _FORMER_NAMES.get(name) if isinstance(name, str) else None
    return former.value if former is not None else name


def spec_of(file_type: FileType | str) -> FileTypeSpec:
    return SPECS[FileType(file_type)]


def type_of_media(media_type: str | None) -> FileType:
    """The type a stored file of ``media_type`` is; ``other`` where none is
    registered for it."""
    media = (media_type or "").split(";", 1)[0].strip().lower()
    return _BY_MEDIA_TYPE.get(media, FileType.other)


def types_of_kind(kind: FileKind) -> tuple[FileType, ...]:
    return tuple(t for t, spec in SPECS.items() if spec.kind is kind)


def is_stored(file_type: FileType | str) -> bool:
    return spec_of(file_type).stored


def export_formats(file_type: FileType | str) -> tuple[str, ...]:
    """What a file of ``file_type`` exports as: the editor's formats for its
    own types, the stored file itself for the rest."""
    spec = spec_of(file_type)
    return ("file",) if spec.stored else spec.exports
