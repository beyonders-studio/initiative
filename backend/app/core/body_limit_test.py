"""Which request bodies the transport bounds, and how tightly."""

from __future__ import annotations

import json

import pytest
from starlette.datastructures import Headers

from app.core.body_limit import (
    DEFAULT_MAX_REQUEST_BYTES,
    DOCUMENT_MAX_REQUEST_BYTES,
    MULTIPART_MAX_REQUEST_BYTES,
    BodySizeLimitMiddleware,
    _bound_for,
)
from app.core.messages import CommonMessages, ImportEngineMessages
from app.main import app
from app.services.import_engine import limits as import_limits
from app.services.marketplace import listing_assets, tool_listings
from app.services.tenant import attachments


def _bound(
    path: str, method: str = "POST", content_type: str = "application/json"
) -> tuple[int, str]:
    """The bound a request to ``path`` gets, resolved against the real app."""
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "root_path": "",
        "headers": [(b"content-type", content_type.encode())],
        "app": app,
    }
    return _bound_for(scope, Headers(scope=scope))


def test_the_atlassian_routes_are_bounded_where_they_are():
    """The connect and the import take a handful of strings; the export
    upload takes a zip as large as a backup."""
    connect = _bound("/api/v1/c/1/imports/atlassian/connect")
    start = _bound("/api/v1/c/1/imports/atlassian/import")
    export = _bound("/api/v1/c/1/imports/atlassian/export")
    assert connect == start
    assert connect[0] < DEFAULT_MAX_REQUEST_BYTES
    assert export[0] > import_limits.IMPORT_MAX_BACKUP_UPLOAD_BYTES
    assert export == _bound("/api/v1/c/1/imports/backup")
    assert {connect[1], export[1]} == {ImportEngineMessages.IMPORT_TOO_LARGE}


def test_a_routes_bound_is_read_when_the_request_arrives(monkeypatch):
    monkeypatch.setattr(import_limits, "IMPORT_MAX_ENVELOPE_BYTES", 1024)
    assert _bound("/api/v1/c/1/imports/envelope") == (
        1024,
        ImportEngineMessages.IMPORT_TOO_LARGE,
    )


def test_a_route_with_no_bound_of_its_own_still_has_one():
    assert _bound("/api/v1/c/1/tasks/") == (
        DEFAULT_MAX_REQUEST_BYTES,
        CommonMessages.REQUEST_TOO_LARGE,
    )
    assert _bound("/api/v1/auth/token") == (
        DEFAULT_MAX_REQUEST_BYTES,
        CommonMessages.REQUEST_TOO_LARGE,
    )


def test_a_multipart_upload_gets_room_for_the_largest_file_a_route_takes():
    limit, _ = _bound(
        "/api/v1/c/1/files/upload",
        content_type="multipart/form-data; boundary=x",
    )
    assert limit == MULTIPART_MAX_REQUEST_BYTES
    assert limit > attachments.MAX_FILE_SIZE
    # A listing sends all of its pictures in one request, beside its body.
    listing = (
        listing_assets.MAX_LISTING_IMAGES * listing_assets.MAX_IMAGE_BYTES
        + tool_listings.MAX_LISTING_BODY_BYTES
    )
    assert limit > listing


def test_the_default_leaves_room_for_a_calendar_import():
    """The largest JSON body no route bounds is an iCalendar import."""
    assert DEFAULT_MAX_REQUEST_BYTES > 2 * 2_000_000


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/c/1/files/"),
        ("PATCH", "/api/v1/c/1/files/42"),
        ("POST", "/api/v1/c/1/wikis/3/pages"),
        ("PATCH", "/api/v1/c/1/wiki-pages/9"),
        ("POST", "/api/v1/c/1/collaboration/files/42/collaborate"),
        ("POST", "/api/v1/c/1/collaboration/wiki-pages/9/collaborate"),
    ],
)
def test_the_routes_that_write_a_file_take_a_whiteboard(method, path):
    assert _bound(path, method)[0] == DOCUMENT_MAX_REQUEST_BYTES


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/c/1/files/42/comments"),
        ("POST", "/api/v1/c/1/files/42/duplicate"),
        ("PATCH", "/api/v1/c/1/wikis/3"),
        ("POST", "/api/v1/c/1/wiki-pages/9/move"),
        ("GET", "/api/v1/c/1/files/42"),
    ],
)
def test_only_the_routes_that_carry_content_take_a_whiteboard(method, path):
    assert _bound(path, method)[0] == DEFAULT_MAX_REQUEST_BYTES


async def _run(
    headers: list[tuple[bytes, bytes]], chunks: list[bytes]
) -> tuple[int, bytes]:
    """Drive the middleware around an app that reads its whole body."""

    async def app(scope, receive, send):
        while (await receive()).get("more_body"):
            pass
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    pending = [
        {"type": "http.request", "body": c, "more_body": i < len(chunks) - 1}
        for i, c in enumerate(chunks)
    ]

    async def receive():
        return pending.pop(0)

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "path": "/api/v1/c/1/tasks/", "headers": headers}
    await BodySizeLimitMiddleware(app)(scope, receive, send)
    return sent[0]["status"], b"".join(m.get("body", b"") for m in sent[1:])


async def test_a_declared_length_over_the_default_is_refused_unread():
    status, body = await _run(
        [(b"content-length", str(DEFAULT_MAX_REQUEST_BYTES + 1).encode())],
        [b""],
    )
    assert status == 413
    assert json.loads(body)["detail"] == CommonMessages.REQUEST_TOO_LARGE


async def test_a_chunked_body_over_the_default_is_cut_off():
    chunk = b"x" * (1024 * 1024)
    status, body = await _run([], [chunk] * 5)
    assert status == 413
    assert json.loads(body)["detail"] == CommonMessages.REQUEST_TOO_LARGE


async def test_a_body_under_the_default_goes_through():
    status, body = await _run([], [b"{}"])
    assert (status, body) == (200, b"ok")
