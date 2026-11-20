"""The listings this build ships with.

One JSON file per listing under ``app/marketplace_catalog/``, loaded and upserted
into the catalog at boot. No network: a FOSS install has a working marketplace
out of the box, and a remote registry (later) adds to the same tables through the
same validator rather than a parallel path.

Seeding is idempotent and runs on the system engine. A file that fails validation
is logged and skipped — one malformed listing must not take the rest of the
catalog, or the boot, with it.

Seeding is also what *removes* a shipped listing. The files are the whole truth
about what this build offers, so anything in the catalog under ``builtin`` that
no longer has a file is withdrawn on the next boot. Without that a listing
dropped from the build stays on the shelf of every database that ever saw it.
Withdrawn is not deleted: a guild that already installed it keeps its plug-in.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.marketplace.catalog import (
    CatalogError,
    published_uids,
    upsert_listing,
    withdraw_builtins_except,
)

if TYPE_CHECKING:
    from app.core.tool_set import ToolSet

logger = logging.getLogger(__name__)

#: Where the shipped manifests live. Repo-relative, copied into the image.
CATALOG_DIR = Path(__file__).resolve().parent.parent.parent / "marketplace_catalog"

__all__ = [
    "CATALOG_DIR",
    "load_builtin_manifests",
    "seed_builtin_listings",
    "shipped_tools",
]


def load_builtin_manifests(directory: Path | None = None) -> Iterator[dict[str, Any]]:
    """Every shipped manifest, in a stable order.

    Sorted by filename so a re-seed touches rows in the same order every time —
    which keeps a failure reproducible rather than depending on the filesystem.
    """
    root = directory or CATALOG_DIR
    if not root.is_dir():
        return
    for path in sorted(root.glob("*.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("marketplace: skipping unreadable listing %s: %s", path, exc)
            continue
        if not isinstance(manifest, dict):
            logger.warning("marketplace: skipping listing %s: not an object", path)
            continue
        yield manifest


@cache
def shipped_tools() -> ToolSet:
    """The built-in tools and those of the tool plug-ins this build ships:
    the datasets a listed dashboard may read. Their kinds take the codes they
    were given where a built-in kind's passed to them, and stand-ins
    otherwise, so this set says what a dashboard may name and is never a
    community's."""
    import sqlalchemy as sa

    from app.core.tool_set import BUILTIN_TOOLS, ToolSet
    from app.db.plugin_tools import InstalledTool, build_tool
    from app.models.platform.plugin_kind_code import (
        ADOPTED_KIND_CODES,
        FIRST_PLUGIN_KIND_CODE,
    )
    from app.services.marketplace.tool_plugins import is_tool_plugin, tool_kinds

    shipped = [
        InstalledTool(manifest["uid"], manifest["definition"])
        for manifest in load_builtin_manifests()
        if manifest.get("kind") == "plugin"
        and is_tool_plugin(manifest.get("definition"))
    ]
    kinds = [
        kind
        for tool in shipped
        for kind in tool_kinds(tool.definition, listing_uid=tool.listing_uid)
    ]
    codes = {
        kind: ADOPTED_KIND_CODES.get(kind, FIRST_PLUGIN_KIND_CODE + index)
        for index, kind in enumerate(kinds)
    }
    metadata = sa.MetaData()
    return ToolSet(
        (*BUILTIN_TOOLS, *(build_tool(tool, codes, metadata) for tool in shipped)),
        digest="shipped",
    )


def _manifest_file_count(directory: Path | None = None) -> int:
    """How many listing files are on disk, readable or not."""
    root = directory or CATALOG_DIR
    return len(list(root.glob("*.json"))) if root.is_dir() else 0


async def seed_builtin_listings(
    session: AsyncSession, directory: Path | None = None
) -> int:
    """Upsert the shipped listings this deployment serves. Returns how many landed.

    Called from startup seeding on the system-engine session. Never raises: a bad
    manifest is a packaging bug to fix, not a reason to refuse to boot.

    A shipped listing that is no longer shipped is withdrawn, so removing a file
    from the build removes it from the shelf everywhere on the next boot rather
    than leaving a row nobody can install. Guilds that already have it keep it.
    """
    seeded = 0
    shipped: list[str] = []
    read = 0
    for manifest in load_builtin_manifests(directory):
        read += 1
        # Recorded before the upsert, not after: a manifest this build ships but
        # cannot validate is a packaging bug to fix, and withdrawing the working
        # listing it replaces would turn that bug into data loss. Every uid the
        # manifest publishes, so the dashboards a plug-in bundles are claimed by
        # the same pass that publishes them.
        shipped.extend(uid for uid in published_uids(manifest) if uid)
        try:
            await upsert_listing(session, manifest, source="builtin")
            seeded += 1
        except CatalogError as exc:
            logger.warning("marketplace: skipping built-in listing: %s", exc)

    # Whatever this build no longer ships stops being offered — but only when
    # the whole shelf was readable. A file that could not be parsed leaves no
    # uid behind, and sweeping on a partial list would withdraw a listing this
    # build does ship.
    on_disk = _manifest_file_count(directory)
    if read < on_disk:
        logger.warning(
            "marketplace: %d of %d built-in listing files unreadable; "
            "not withdrawing anything this pass",
            on_disk - read,
            on_disk,
        )
        return seeded

    withdrawn = await withdraw_builtins_except(session, shipped)
    if withdrawn:
        logger.info(
            "marketplace: withdrew %d built-in listing(s) this build no longer ships",
            withdrawn,
        )
    return seeded
