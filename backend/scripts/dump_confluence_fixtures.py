"""Capture one Confluence space's page bodies as test fixtures.

The storage-format walker is tested against real pages as well as the
snippets in its own test file, because what the editor actually writes is
the thing worth being right about. This fetches every current page of one
space in storage format and writes each body, plus an index of the tree, to
``app/services/import_engine/fixtures/confluence/``.

    cd backend
    ATLASSIAN_SITE=https://acme.atlassian.net \\
    ATLASSIAN_EMAIL=you@example.com \\
    ATLASSIAN_TOKEN=... \\
    uv run python scripts/dump_confluence_fixtures.py IMPTEST

The token is read from the environment and never written anywhere. Read what
the script wrote before committing it: a page body is whatever somebody typed.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.import_engine.atlassian import (
    AtlassianCredential,
    get_json,
    normalize_site_url,
)

OUT = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "import_engine"
    / "fixtures"
    / "confluence"
)


def _slug(title: str) -> str:
    # Short enough that the path stays well inside what every filesystem a
    # contributor checks out on will take.
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50].strip("-")
    return slug or "page"


def _next_path(payload: dict) -> str | None:
    link = (payload.get("_links") or {}).get("next")
    if not link:
        return None
    return link if link.startswith("/wiki/") else f"/wiki{link}"


async def main(space_key: str) -> None:
    credential = AtlassianCredential(
        site_url=normalize_site_url(os.environ["ATLASSIAN_SITE"]),
        email=os.environ["ATLASSIAN_EMAIL"],
        api_token=os.environ["ATLASSIAN_TOKEN"],
    )
    spaces = await get_json(credential, f"/wiki/api/v2/spaces?keys={space_key}")
    results = spaces.get("results") if isinstance(spaces, dict) else None
    if not isinstance(results, list) or not results:
        raise SystemExit(f"No space {space_key!r} that this token can read.")
    space = results[0]
    assert isinstance(space, dict)

    OUT.mkdir(parents=True, exist_ok=True)
    index = {
        "space": {
            "id": space.get("id"),
            "key": space.get("key"),
            "name": space.get("name"),
            "homepageId": space.get("homepageId"),
        },
        "pages": [],
    }
    path: str | None = (
        f"/wiki/api/v2/spaces/{space['id']}/pages?body-format=storage&limit=250"
    )
    while path:
        payload = await get_json(credential, path)
        assert isinstance(payload, dict)
        pages = payload.get("results")
        for page in pages if isinstance(pages, list) else []:
            assert isinstance(page, dict)
            name = f"{page['id']}-{_slug(page.get('title') or '')}.xml"
            body = ((page.get("body") or {}).get("storage") or {}).get("value") or ""
            (OUT / name).write_text(body, encoding="utf-8")
            index["pages"].append(
                {
                    "id": page.get("id"),
                    "title": page.get("title"),
                    "parentId": page.get("parentId"),
                    "parentType": page.get("parentType"),
                    "position": page.get("position"),
                    "status": page.get("status"),
                    "file": name,
                }
            )
        path = _next_path(payload)

    (OUT / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    print(f"Wrote {len(index['pages'])} pages to {OUT}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: dump_confluence_fixtures.py SPACE_KEY")
    asyncio.run(main(sys.argv[1]))
