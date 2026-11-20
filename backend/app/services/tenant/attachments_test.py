"""Unit tests for the attachments service helpers."""

import pytest


def test_a_description_s_pictures_are_read_out_of_its_markdown():
    from app.services.tenant.attachments import upload_urls_in_markdown

    text = (
        "Before ![a](/uploads/9/task-abc_1.png) and "
        "![b](https://example.com/uploads/9/task-def.jpg), "
        "a link [c](/uploads/9/doc.pdf) and /api/v1/uploads-nope"
    )

    assert upload_urls_in_markdown(text) == {
        "/uploads/9/task-abc_1.png",
        "/uploads/9/task-def.jpg",
        "/uploads/9/doc.pdf",
    }
    assert upload_urls_in_markdown(None) == set()


@pytest.mark.parametrize(
    ("extension", "prefix", "shape"),
    [
        (".pdf", "", r"[0-9a-f]{32}\.pdf"),
        ("pdf", "", r"[0-9a-f]{32}\.pdf"),
        ("", "", r"[0-9a-f]{32}"),
        (".png", "pasted-", r"pasted-[0-9a-f]{32}\.png"),
    ],
)
def test_a_new_upload_name_is_random_and_keeps_its_extension(extension, prefix, shape):
    import re

    from app.services.tenant.attachments import new_upload_filename

    assert re.fullmatch(shape, new_upload_filename(extension, prefix=prefix))


def _word_document() -> bytes:
    import io

    import docx

    buffer = io.BytesIO()
    docx.Document().save(buffer)
    return buffer.getvalue()


def _zip_of(*names: str) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, "hello")
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("content", "filename", "expected"),
    [
        (b"%PDF-1.4 body", "report.pdf", ("application/pdf", ".pdf")),
        # Plain text takes the kind of text its name says.
        (b"# Title\n\nSome text\n", "notes.md", ("text/markdown", ".md")),
        # A package libmagic reads only as bytes is an Office file when it
        # holds one.
        (
            _word_document(),
            "brief.docx",
            (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".docx",
            ),
        ),
        # The bytes win over a name they contradict.
        (
            b"<!doctype html><html><body>x</body></html>",
            "invoice.pdf",
            ("text/html", ".html"),
        ),
        (_zip_of("notes.txt"), "brief.docx", ("application/zip", ".zip")),
        (b"a,b\n1,2\n3,4\n", "totals.csv", ("text/csv", ".csv")),
        (b'{"a": [1, 2]}', "data.json", ("application/json", ".json")),
        # A format the registry doesn't name is still taken, and stored
        # without an extension of its own.
        (b"\x00\x01\x02\x03" * 64, "dump.bin", ("application/octet-stream", "")),
        # A format whose bytes borrow a family's is named by its name, within
        # what its bytes may read as.
        (b"%PDF-1.6\n" + b"\x00" * 64, "logo.ai", ("application/illustrator", ".ai")),
        (
            _zip_of("document.json"),
            "poster.sketch",
            ("application/x-sketch", ".sketch"),
        ),
        (b"import os\nprint(os.name)\n", "build.py", ("text/x-python", ".py")),
        (b"package main\n\nfunc main() {}\n", "main.go", ("text/x-go", ".go")),
        (
            b"II*\x00\x08\x00\x00\x00" + b"\x00" * 64,
            "shot.dng",
            ("image/x-adobe-dng", ".dng"),
        ),
        # ... and never past it: an HTML page named as script is still HTML.
        (
            b"<!doctype html><html><body>x</body></html>",
            "app.js",
            ("text/html", ".html"),
        ),
        # A format its bytes name is that format whatever it is called.
        (
            b"8BPS\x00\x01"
            + b"\x00" * 6
            + b"\x00\x03\x00\x00\x01\x00\x00\x00\x01\x00\x00\x08\x00\x03"
            + b"\x00" * 64,
            "poster.bin",
            ("image/vnd.adobe.photoshop", ".psd"),
        ),
    ],
    ids=[
        "pdf",
        "markdown",
        "office-package",
        "html-named-pdf",
        "zip-named-docx",
        "csv",
        "json",
        "unknown",
        "pdf-named-ai",
        "zip-named-sketch",
        "text-named-py",
        "c-like-named-go",
        "tiff-named-dng",
        "html-named-js",
        "psd-by-bytes",
    ],
)
def test_an_upload_s_type_is_read_from_its_bytes(content, filename, expected):
    from app.services.tenant.attachments import validate_file

    assert validate_file(content, filename) == expected


@pytest.mark.parametrize(
    ("content", "filename"),
    [
        (b"MZ\x90\x00" + b"\x00" * 60 + b"PE\x00\x00", "invoice.pdf"),
        (b"\x7fELF\x02\x01\x01" + b"\x00" * 9 + b"\x02\x00>\x00" + b"\x00" * 64, "run"),
        (b"echo hello\n", "setup.sh"),
        (b"#!/bin/sh\necho hello\n", "notes.txt"),
        (b"@echo off\r\necho hello\r\n", "notes.txt"),
        (b"echo hello\n", "setup.bat. "),
        (b"echo hello\n", "setup.b\u200bat"),
        (_zip_of("AndroidManifest.xml", "classes.dex"), "photos.zip"),
    ],
    ids=[
        "program-named-pdf",
        "linux-program",
        "script",
        "shell-script-named-txt",
        "batch-file-named-txt",
        "trailing-dot-and-space",
        "hidden-character",
        "android-app",
    ],
)
def test_a_program_is_refused_whatever_it_is_named(content, filename):
    from app.services.tenant.attachments import RefusedFileTypeError, validate_file

    with pytest.raises(RefusedFileTypeError):
        validate_file(content, filename)


@pytest.mark.parametrize(
    ("name", "shown"),
    [
        ("report\u202egnp.exe", "reportgnp.exe"),
        ("  notes.txt. ", "notes.txt"),
        ("\u200b", None),
        ("a" * 300 + ".pdf", "a" * 251 + ".pdf"),
    ],
)
def test_a_file_name_is_kept_as_it_can_be_shown(name, shown):
    from app.services.tenant.attachments import display_filename

    assert display_filename(name) == shown
