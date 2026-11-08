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
    rar = "rar"
    ai = "ai"
    psd = "psd"
    eps = "eps"
    indd = "indd"
    xcf = "xcf"
    kra = "kra"
    procreate = "procreate"
    clip = "clip"
    sketch = "sketch"
    fig = "fig"
    afdesign = "afdesign"
    afphoto = "afphoto"
    afpub = "afpub"
    cdr = "cdr"
    blend = "blend"
    fbx = "fbx"
    obj = "obj"
    stl = "stl"
    glb = "glb"
    gltf = "gltf"
    three_mf = "3mf"
    usdz = "usdz"
    ttf = "ttf"
    otf = "otf"
    woff = "woff"
    woff2 = "woff2"
    dng = "dng"
    cr2 = "cr2"
    cr3 = "cr3"
    nef = "nef"
    arw = "arw"
    raf = "raf"
    orf = "orf"
    py = "py"
    js = "js"
    ts = "ts"
    css = "css"
    sql = "sql"
    yaml = "yaml"
    xml = "xml"
    toml = "toml"
    c = "c"
    cpp = "cpp"
    cs = "cs"
    java = "java"
    go = "go"
    rs = "rs"
    rb = "rb"
    php = "php"
    swift = "swift"
    kt = "kt"
    epub = "epub"
    mobi = "mobi"
    dwg = "dwg"
    dxf = "dxf"
    step = "step"
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
    compressed = "compressed"
    design = "design"
    three_d = "3d"
    font = "font"
    raw = "raw"
    code = "code"
    ebook = "ebook"
    cad = "cad"
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
    #: The format Pillow reads it as, for a type the app makes a thumbnail of.
    picture_format: str | None = None
    #: The editor's own type an uploaded file of this type becomes when
    #: somebody converts it to edit it (``app.services.tenant.file_conversion``).
    converts_to: FileType | None = None
    #: What a file of this type's bytes may read as when they say no more
    #: than the family (a zip, plain text, a PDF): a file whose bytes say one
    #: of these and whose name says this type is this type.
    containers: tuple[str, ...] = ()

    @property
    def stored(self) -> bool:
        """Whether a file of this type is stored versions rather than a body
        the editor keeps in the database."""
        return bool(self.media_types)


def _stored(
    kind: FileKind,
    media_types: tuple[str, ...],
    *extensions: str,
    picture_format: str | None = None,
    converts_to: FileType | None = None,
    containers: tuple[str, ...] = (),
) -> FileTypeSpec:
    return FileTypeSpec(
        kind,
        media_types,
        extensions,
        picture_format=picture_format,
        converts_to=converts_to,
        containers=containers,
    )


_OOXML = "application/vnd.openxmlformats-officedocument"
_ODF = "application/vnd.oasis.opendocument"
#: What the bytes of a file in a format of its own often say instead.
_ZIP = ("application/zip",)
_BINARY = ("application/octet-stream",)
_TEXT = ("text/plain",)
_TIFF = ("image/tiff",)
#: What libmagic calls source in languages it does not tell apart.
_C_LIKE = ("text/plain", "text/x-c", "text/x-c++")

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
        FileKind.document,
        (f"{_OOXML}.wordprocessingml.document",),
        ".docx",
        converts_to=FileType.lexical,
    ),
    FileType.odt: _stored(
        FileKind.document, (f"{_ODF}.text",), ".odt", converts_to=FileType.lexical
    ),
    FileType.rtf: _stored(FileKind.document, ("text/rtf", "application/rtf"), ".rtf"),
    FileType.md: _stored(
        FileKind.document,
        ("text/markdown", "text/x-markdown"),
        ".md",
        ".markdown",
        converts_to=FileType.lexical,
    ),
    FileType.xls: _stored(
        FileKind.spreadsheet,
        ("application/vnd.ms-excel",),
        ".xls",
        converts_to=FileType.sheet,
    ),
    FileType.xlsx: _stored(
        FileKind.spreadsheet,
        (f"{_OOXML}.spreadsheetml.sheet",),
        ".xlsx",
        converts_to=FileType.sheet,
    ),
    FileType.ods: _stored(
        FileKind.spreadsheet,
        (f"{_ODF}.spreadsheet",),
        ".ods",
        converts_to=FileType.sheet,
    ),
    FileType.csv: _stored(
        FileKind.spreadsheet, ("text/csv",), ".csv", converts_to=FileType.sheet
    ),
    FileType.tsv: _stored(
        FileKind.spreadsheet,
        ("text/tab-separated-values",),
        ".tsv",
        converts_to=FileType.sheet,
    ),
    FileType.ppt: _stored(
        FileKind.presentation, ("application/vnd.ms-powerpoint",), ".ppt"
    ),
    FileType.pptx: _stored(
        FileKind.presentation, (f"{_OOXML}.presentationml.presentation",), ".pptx"
    ),
    FileType.odp: _stored(FileKind.presentation, (f"{_ODF}.presentation",), ".odp"),
    FileType.png: _stored(FileKind.image, ("image/png",), ".png", picture_format="PNG"),
    FileType.jpeg: _stored(
        FileKind.image,
        ("image/jpeg", "image/jpg"),
        ".jpg",
        ".jpeg",
        picture_format="JPEG",
    ),
    FileType.gif: _stored(FileKind.image, ("image/gif",), ".gif", picture_format="GIF"),
    FileType.webp: _stored(
        FileKind.image, ("image/webp",), ".webp", picture_format="WEBP"
    ),
    FileType.svg: _stored(FileKind.image, ("image/svg+xml",), ".svg"),
    FileType.heic: _stored(
        FileKind.image, ("image/heic", "image/heif"), ".heic", ".heif"
    ),
    FileType.tiff: _stored(
        FileKind.image, ("image/tiff",), ".tiff", ".tif", picture_format="TIFF"
    ),
    FileType.mp4: _stored(FileKind.video, ("video/mp4",), ".mp4", ".m4v"),
    FileType.webm: _stored(FileKind.video, ("video/webm",), ".webm"),
    FileType.mov: _stored(FileKind.video, ("video/quicktime",), ".mov"),
    FileType.mp3: _stored(FileKind.audio, ("audio/mpeg",), ".mp3"),
    FileType.m4a: _stored(FileKind.audio, ("audio/mp4", "audio/x-m4a"), ".m4a"),
    FileType.wav: _stored(FileKind.audio, ("audio/wav", "audio/x-wav"), ".wav"),
    FileType.ogg: _stored(FileKind.audio, ("audio/ogg",), ".ogg", ".oga"),
    FileType.flac: _stored(FileKind.audio, ("audio/flac",), ".flac"),
    FileType.txt: _stored(
        FileKind.text, ("text/plain",), ".txt", converts_to=FileType.lexical
    ),
    FileType.json: _stored(FileKind.text, ("application/json",), ".json"),
    FileType.html: _stored(FileKind.text, ("text/html",), ".html", ".htm"),
    FileType.zip: _stored(FileKind.compressed, ("application/zip",), ".zip"),
    FileType.tar: _stored(FileKind.compressed, ("application/x-tar",), ".tar"),
    FileType.gz: _stored(FileKind.compressed, ("application/gzip",), ".gz", ".tgz"),
    FileType.seven_zip: _stored(
        FileKind.compressed, ("application/x-7z-compressed",), ".7z"
    ),
    FileType.rar: _stored(
        FileKind.compressed, ("application/vnd.rar", "application/x-rar"), ".rar"
    ),
    FileType.ai: _stored(
        FileKind.design,
        ("application/illustrator",),
        ".ai",
        containers=("application/pdf", "application/postscript"),
    ),
    FileType.psd: _stored(
        FileKind.design, ("image/vnd.adobe.photoshop",), ".psd", ".psb"
    ),
    FileType.eps: _stored(
        FileKind.design,
        ("application/postscript", "image/x-eps"),
        ".eps",
        ".ps",
    ),
    FileType.indd: _stored(
        FileKind.design, ("application/x-indesign",), ".indd", containers=_BINARY
    ),
    FileType.xcf: _stored(FileKind.design, ("image/x-xcf",), ".xcf"),
    FileType.kra: _stored(
        FileKind.design, ("application/x-krita",), ".kra", containers=_ZIP
    ),
    FileType.procreate: _stored(
        FileKind.design, ("application/x-procreate",), ".procreate", containers=_ZIP
    ),
    FileType.clip: _stored(
        FileKind.design, ("application/x-clip-studio",), ".clip", containers=_BINARY
    ),
    FileType.sketch: _stored(
        FileKind.design, ("application/x-sketch",), ".sketch", containers=_ZIP
    ),
    FileType.fig: _stored(
        FileKind.design, ("application/x-fig",), ".fig", containers=_BINARY
    ),
    FileType.afdesign: _stored(
        FileKind.design, ("application/x-afdesign",), ".afdesign", containers=_BINARY
    ),
    FileType.afphoto: _stored(
        FileKind.design, ("application/x-afphoto",), ".afphoto", containers=_BINARY
    ),
    FileType.afpub: _stored(
        FileKind.design, ("application/x-afpub",), ".afpub", containers=_BINARY
    ),
    FileType.cdr: _stored(FileKind.design, ("application/vnd.corel-draw",), ".cdr"),
    FileType.blend: _stored(
        FileKind.three_d, ("application/x-blender",), ".blend", containers=_BINARY
    ),
    FileType.fbx: _stored(
        FileKind.three_d, ("application/x-fbx",), ".fbx", containers=_BINARY
    ),
    FileType.obj: _stored(FileKind.three_d, ("model/obj",), ".obj", containers=_TEXT),
    FileType.stl: _stored(
        FileKind.three_d, ("model/stl",), ".stl", containers=_TEXT + _BINARY
    ),
    FileType.glb: _stored(FileKind.three_d, ("model/gltf-binary",), ".glb"),
    FileType.gltf: _stored(
        FileKind.three_d,
        ("model/gltf+json",),
        ".gltf",
        containers=("application/json",),
    ),
    FileType.three_mf: _stored(
        FileKind.three_d, ("model/3mf",), ".3mf", containers=_ZIP
    ),
    FileType.usdz: _stored(
        FileKind.three_d, ("model/vnd.usdz+zip",), ".usdz", containers=_ZIP
    ),
    FileType.ttf: _stored(FileKind.font, ("font/ttf", "font/sfnt"), ".ttf"),
    FileType.otf: _stored(
        FileKind.font,
        ("font/otf", "application/vnd.ms-opentype"),
        ".otf",
        containers=("font/sfnt",),
    ),
    FileType.woff: _stored(FileKind.font, ("font/woff",), ".woff", containers=_BINARY),
    FileType.woff2: _stored(
        FileKind.font, ("font/woff2",), ".woff2", containers=_BINARY
    ),
    FileType.dng: _stored(
        FileKind.raw, ("image/x-adobe-dng",), ".dng", containers=_TIFF
    ),
    FileType.cr2: _stored(
        FileKind.raw, ("image/x-canon-cr2",), ".cr2", containers=_TIFF
    ),
    FileType.cr3: _stored(
        FileKind.raw, ("image/x-canon-cr3",), ".cr3", containers=_BINARY
    ),
    FileType.nef: _stored(
        FileKind.raw, ("image/x-nikon-nef",), ".nef", containers=_TIFF
    ),
    FileType.arw: _stored(
        FileKind.raw, ("image/x-sony-arw",), ".arw", containers=_TIFF
    ),
    FileType.raf: _stored(FileKind.raw, ("image/x-fuji-raf",), ".raf"),
    FileType.orf: _stored(FileKind.raw, ("image/x-olympus-orf",), ".orf"),
    FileType.py: _stored(
        FileKind.code,
        ("text/x-python", "text/x-script.python"),
        ".py",
        containers=_TEXT,
    ),
    FileType.js: _stored(
        FileKind.code,
        ("text/javascript", "application/javascript"),
        ".js",
        ".mjs",
        ".cjs",
        containers=_TEXT,
    ),
    FileType.ts: _stored(
        FileKind.code, ("text/x-typescript",), ".ts", ".tsx", containers=_TEXT
    ),
    FileType.css: _stored(FileKind.code, ("text/css",), ".css", containers=_TEXT),
    FileType.sql: _stored(
        FileKind.code, ("application/sql",), ".sql", containers=_TEXT
    ),
    FileType.yaml: _stored(
        FileKind.code,
        ("application/yaml", "text/yaml"),
        ".yaml",
        ".yml",
        containers=_TEXT,
    ),
    FileType.xml: _stored(
        FileKind.code, ("text/xml", "application/xml"), ".xml", containers=_TEXT
    ),
    FileType.toml: _stored(
        FileKind.code, ("application/toml",), ".toml", containers=_TEXT
    ),
    FileType.c: _stored(FileKind.code, ("text/x-c",), ".c", ".h", containers=_TEXT),
    FileType.cpp: _stored(
        FileKind.code,
        ("text/x-c++",),
        ".cpp",
        ".cc",
        ".cxx",
        ".hpp",
        containers=_C_LIKE,
    ),
    FileType.cs: _stored(FileKind.code, ("text/x-csharp",), ".cs", containers=_C_LIKE),
    FileType.java: _stored(
        FileKind.code, ("text/x-java",), ".java", containers=_C_LIKE
    ),
    FileType.go: _stored(FileKind.code, ("text/x-go",), ".go", containers=_C_LIKE),
    FileType.rs: _stored(FileKind.code, ("text/x-rust",), ".rs", containers=_C_LIKE),
    FileType.rb: _stored(FileKind.code, ("text/x-ruby",), ".rb", containers=_TEXT),
    FileType.php: _stored(FileKind.code, ("text/x-php",), ".php", containers=_TEXT),
    FileType.swift: _stored(
        FileKind.code, ("text/x-swift",), ".swift", containers=_C_LIKE
    ),
    FileType.kt: _stored(
        FileKind.code, ("text/x-kotlin",), ".kt", ".kts", containers=_C_LIKE
    ),
    FileType.epub: _stored(FileKind.ebook, ("application/epub+zip",), ".epub"),
    FileType.mobi: _stored(
        FileKind.ebook,
        ("application/x-mobipocket-ebook",),
        ".mobi",
        containers=_BINARY,
    ),
    FileType.dwg: _stored(FileKind.cad, ("image/vnd.dwg",), ".dwg"),
    FileType.dxf: _stored(
        FileKind.cad, ("image/vnd.dxf", "application/x-dxf"), ".dxf", containers=_TEXT
    ),
    FileType.step: _stored(
        FileKind.cad, ("model/step",), ".step", ".stp", containers=_TEXT
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
