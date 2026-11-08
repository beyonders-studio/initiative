"""The help center's search index: served as the image built it, or empty."""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

from app.api.v1.platform_endpoints import help_center

BUILT = {
    "items": [
        {
            "title": "My invite link doesn't work",
            "section": "FAQ › Getting in",
            "location": "en/faq/#my-invite-link-doesnt-work",
            "snippet": "Links can expire, run out of uses, or be switched off by an "
            "admin. Use <name> as written.",
        }
    ]
}


@pytest.fixture
def index_at(monkeypatch):
    """Point the route at ``path``, read afresh."""

    def point(path) -> None:
        monkeypatch.setattr(help_center, "INDEX_PATH", path)
        help_center._served.cache_clear()

    yield point
    help_center._served.cache_clear()


@pytest.mark.parametrize("built", [BUILT, None], ids=["built", "absent"])
async def test_the_index_is_what_the_image_built(
    client: AsyncClient, tmp_path, index_at, built
):
    path = tmp_path / "help-index.json"
    if built is not None:
        path.write_text(json.dumps(built), encoding="utf-8")
    index_at(path)

    response = await client.get("/api/v1/help/index")
    assert response.status_code == 200, response.text
    assert response.json() == (built or {"items": []})
    assert response.headers["cache-control"] == "public, max-age=3600"
