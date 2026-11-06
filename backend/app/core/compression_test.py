"""Which responses are gzipped."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.compression import TextCompressionMiddleware, compressible, takes_gzip

_BODY = b"x" * 4096


def _client() -> TestClient:
    def answer(media_type: str, status: int = 200):
        return lambda _request: Response(
            _BODY, status_code=status, media_type=media_type
        )

    app = Starlette(
        routes=[
            Route("/json", answer("application/json")),
            Route("/picture", answer("image/png")),
            Route("/part", answer("text/csv", 206)),
            Route("/small", lambda _r: Response(b"{}", media_type="application/json")),
        ]
    )
    app.add_middleware(TextCompressionMiddleware, minimum_size=1024, compresslevel=6)
    return TestClient(app)


@pytest.mark.parametrize(
    ("path", "gzipped"),
    [("/json", True), ("/picture", False), ("/part", False), ("/small", False)],
)
def test_only_text_worth_shrinking_is_gzipped(path, gzipped):
    response = _client().get(path, headers={"Accept-Encoding": "gzip"})

    assert (response.headers.get("content-encoding") == "gzip") is gzipped
    if path != "/small":
        assert response.content == _BODY


@pytest.mark.parametrize("accept", ["identity", "gzip;q=0, identity", "*;q=0"])
def test_a_client_that_takes_no_gzip_gets_none(accept):
    response = _client().get("/json", headers={"Accept-Encoding": accept})

    assert "content-encoding" not in response.headers


@pytest.mark.parametrize(
    ("accept", "takes"),
    [
        ("gzip", True),
        ("br, gzip;q=0.5", True),
        ("*", True),
        ("gzip;q=0, *", False),
        ("gzip;q=nope", False),
        ("", False),
    ],
)
def test_gzip_is_taken_only_with_a_quality_above_zero(accept, takes):
    assert takes_gzip(accept) is takes


@pytest.mark.parametrize(
    ("content_type", "shrinks"),
    [
        ("application/json", True),
        ("text/html; charset=utf-8", True),
        ("image/svg+xml", True),
        ("application/vnd.api+json", True),
        ("text/event-stream", False),
        ("application/jsonl", False),
        ("video/mp4", False),
        ("application/zip", False),
    ],
)
def test_text_like_types_shrink(content_type, shrinks):
    assert compressible(content_type) is shrinks
