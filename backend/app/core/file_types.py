"""What a file is: its type, and the kind that decides how it is shown.

A file's **type** is its format: the editor's own formats (``lexical``,
``excalidraw``, ``sheet``, ``url``) and the formats an upload can be (``pdf``,
``docx``, ``png`` …), with ``other`` for anything else. Its **kind** follows
from the type: a ``sheet``, an ``xlsx`` and a ``csv`` are all spreadsheets.

The type is what ``files.file_type`` stores. The kind is never stored; a
filter by kind reads :func:`types_of_kind`.

An upload may be any format but a program: :func:`is_refused`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class FileType(str, Enum):
    lexical = "lexical"
    excalidraw = "excalidraw"
    sheet = "sheet"
    url = "url"
    pdf = "pdf"
    doc = "doc"
    docx = "docx"
    odt = "odt"
    rtf = "rtf"
    md = "md"
    xls = "xls"
    xlsx = "xlsx"
    ods = "ods"
    csv = "csv"
    tsv = "tsv"
    ppt = "ppt"
    pptx = "pptx"
    odp = "odp"
    png = "png"
    jpeg = "jpeg"
    gif = "gif"
    webp = "webp"
    svg = "svg"
    heic = "heic"
    tiff = "tiff"
    mp4 = "mp4"
    webm = "webm"
    mov = "mov"
    mp3 = "mp3"
    m4a = "m4a"
    wav = "wav"
    ogg = "ogg"
    flac = "flac"
    txt = "txt"
    json = "json"
    html = "html"
    zip = "zip"
    tar = "tar"
    gz = "gz"
    seven_zip = "7z"
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
    #: The extensions a file of this type is named with, the one it is stored
    #: under first.
    extensions: tuple[str, ...] = ()
    #: For the editor's own types: what an export of one may be written as.
    #: Every other type exports as its stored file.
    exports: tuple[str, ...] = ()

    @property
    def stored(self) -> bool:
        """Whether a file of this type is stored versions rather than a body
        the editor keeps in the database."""
        return bool(self.media_types)


def _stored(
    kind: FileKind, media_types: tuple[str, ...], *extensions: str
) -> FileTypeSpec:
    return FileTypeSpec(kind, media_types, extensions)


_OOXML = "application/vnd.openxmlformats-officedocument"
_ODF = "application/vnd.oasis.opendocument"

SPECS: dict[FileType, FileTypeSpec] = {
    FileType.lexical: FileTypeSpec(
        FileKind.document, exports=("json", "md", "pdf", "docx")
    ),
    FileType.excalidraw: FileTypeSpec(FileKind.whiteboard, exports=("json",)),
    FileType.sheet: FileTypeSpec(FileKind.spreadsheet, exports=("csv", "xlsx", "json")),
    FileType.url: FileTypeSpec(FileKind.link, exports=("md", "json")),
    FileType.pdf: _stored(FileKind.pdf, ("application/pdf",), ".pdf"),
    FileType.doc: _stored(FileKind.document, ("application/msword",), ".doc"),
    FileType.docx: _stored(
        FileKind.document, (f"{_OOXML}.wordprocessingml.document",), ".docx"
    ),
    FileType.odt: _stored(FileKind.document, (f"{_ODF}.text",), ".odt"),
    FileType.rtf: _stored(FileKind.document, ("text/rtf", "application/rtf"), ".rtf"),
    FileType.md: _stored(
        FileKind.document, ("text/markdown", "text/x-markdown"), ".md", ".markdown"
    ),
    FileType.xls: _stored(FileKind.spreadsheet, ("application/vnd.ms-excel",), ".xls"),
    FileType.xlsx: _stored(
        FileKind.spreadsheet, (f"{_OOXML}.spreadsheetml.sheet",), ".xlsx"
    ),
    FileType.ods: _stored(FileKind.spreadsheet, (f"{_ODF}.spreadsheet",), ".ods"),
    FileType.csv: _stored(FileKind.spreadsheet, ("text/csv",), ".csv"),
    FileType.tsv: _stored(FileKind.spreadsheet, ("text/tab-separated-values",), ".tsv"),
    FileType.ppt: _stored(
        FileKind.presentation, ("application/vnd.ms-powerpoint",), ".ppt"
    ),
    FileType.pptx: _stored(
        FileKind.presentation, (f"{_OOXML}.presentationml.presentation",), ".pptx"
    ),
    FileType.odp: _stored(FileKind.presentation, (f"{_ODF}.presentation",), ".odp"),
    FileType.png: _stored(FileKind.image, ("image/png",), ".png"),
    FileType.jpeg: _stored(
        FileKind.image, ("image/jpeg", "image/jpg"), ".jpg", ".jpeg"
    ),
    FileType.gif: _stored(FileKind.image, ("image/gif",), ".gif"),
    FileType.webp: _stored(FileKind.image, ("image/webp",), ".webp"),
    FileType.svg: _stored(FileKind.image, ("image/svg+xml",), ".svg"),
    FileType.heic: _stored(
        FileKind.image, ("image/heic", "image/heif"), ".heic", ".heif"
    ),
    FileType.tiff: _stored(FileKind.image, ("image/tiff",), ".tiff", ".tif"),
    FileType.mp4: _stored(FileKind.video, ("video/mp4",), ".mp4", ".m4v"),
    FileType.webm: _stored(FileKind.video, ("video/webm",), ".webm"),
    FileType.mov: _stored(FileKind.video, ("video/quicktime",), ".mov"),
    FileType.mp3: _stored(FileKind.audio, ("audio/mpeg",), ".mp3"),
    FileType.m4a: _stored(FileKind.audio, ("audio/mp4", "audio/x-m4a"), ".m4a"),
    FileType.wav: _stored(FileKind.audio, ("audio/wav", "audio/x-wav"), ".wav"),
    FileType.ogg: _stored(FileKind.audio, ("audio/ogg",), ".ogg", ".oga"),
    FileType.flac: _stored(FileKind.audio, ("audio/flac",), ".flac"),
    FileType.txt: _stored(FileKind.text, ("text/plain",), ".txt"),
    FileType.json: _stored(FileKind.text, ("application/json",), ".json"),
    FileType.html: _stored(FileKind.text, ("text/html",), ".html", ".htm"),
    FileType.zip: _stored(FileKind.archive, ("application/zip",), ".zip"),
    FileType.tar: _stored(FileKind.archive, ("application/x-tar",), ".tar"),
    FileType.gz: _stored(FileKind.archive, ("application/gzip",), ".gz", ".tgz"),
    FileType.seven_zip: _stored(
        FileKind.archive, ("application/x-7z-compressed",), ".7z"
    ),
    FileType.other: _stored(FileKind.other, ("application/octet-stream",)),
}

#: The types the editor creates and keeps as a body.
EDITOR_TYPES = tuple(t for t, spec in SPECS.items() if not spec.stored)

#: Programs, and the scripts whose bytes say so, whatever they are named.
REFUSED_MEDIA_TYPES = frozenset(
    {
        "text/x-shellscript",
        "text/x-msdos-batch",
        "application/x-dosexec",
        "application/x-msdownload",
        "application/vnd.microsoft.portable-executable",
        "application/x-msi",
        "application/x-executable",
        "application/x-pie-executable",
        "application/x-sharedlib",
        "application/x-mach-binary",
        "application/java-archive",
        "application/x-java-applet",
        "application/vnd.android.package-archive",
    }
)
#: Programs and scripts by name: most scripts' bytes are only text.
REFUSED_EXTENSIONS = frozenset(
    {
        ".exe", ".dll", ".msi", ".jar", ".apk", ".ipa",
        ".bat", ".cmd", ".com", ".scr", ".ps1", ".vbs", ".vbe", ".wsf",
        ".hta", ".lnk", ".reg", ".sh", ".app", ".dmg", ".pkg",
    }
)  # fmt: skip

_BY_MEDIA_TYPE = {
    media: file_type for file_type, spec in SPECS.items() for media in spec.media_types
}
_BY_EXTENSION = {
    extension: file_type
    for file_type, spec in SPECS.items()
    for extension in spec.extensions
}


def spec_of(file_type: FileType | str) -> FileTypeSpec:
    return SPECS[FileType(file_type)]


def type_of_media(media_type: str | None) -> FileType:
    """The type a stored file of ``media_type`` is; ``other`` where none is
    registered for it."""
    media = (media_type or "").split(";", 1)[0].strip().lower()
    return _BY_MEDIA_TYPE.get(media, FileType.other)


def type_of_name(filename: str | None) -> FileType | None:
    """The type ``filename``'s extension names, if it names one."""
    return _BY_EXTENSION.get(Path(filename or "").suffix.lower())


def is_refused(media_type: str | None, filename: str | None) -> bool:
    """Whether a file of ``media_type`` named ``filename`` is a program, which
    is never stored."""
    media = (media_type or "").split(";", 1)[0].strip().lower()
    suffix = Path(filename or "").suffix.lower()
    return media in REFUSED_MEDIA_TYPES or suffix in REFUSED_EXTENSIONS


def types_of_kind(kind: FileKind) -> tuple[FileType, ...]:
    return tuple(t for t, spec in SPECS.items() if spec.kind is kind)


def is_stored(file_type: FileType | str) -> bool:
    return spec_of(file_type).stored


def export_formats(file_type: FileType | str) -> tuple[str, ...]:
    """What a file of ``file_type`` exports as: the editor's formats for its
    own types, the stored file itself for the rest."""
    spec = spec_of(file_type)
    return ("file",) if spec.stored else spec.exports
