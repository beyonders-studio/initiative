"""Listings an operator publishes by putting files in a directory.

``MARKETPLACE_EXTRA_CATALOG_DIR`` names a directory of manifests — the same
shape the shipped catalog uses — that this deployment publishes as its own.
Someone who authors a dashboard, or who wants to run a third party's, mounts a
volume, drops JSON in, and it is in their marketplace. **No change to this
repository is involved**, which is the point: publishing is not a fork, a pull
request, or a release.

Where the trust comes from is what makes this a source of its own. A built-in
was shipped here; a registry listing carries a signature this deployment
verifies. One of these carries neither, and needs neither: the operator
controls the volume, so the file being there *is* their decision to publish it.
That is why the catalog records ``source="operator"`` and the marketplace shows
it as added by the deployment's operator rather than as anything endorsed
from here.

Everything else is the ordinary path. Manifests go through ``upsert_listing``,
so an operator listing is held to the same validation, the same uid and
``public_id`` rules, the same required attribution, and the same same-origin
artwork rule as everything else in the catalog. The ``core.*`` namespace stays
with the build. A plug-in's manifest may carry the registry's ``registration``
block, and its scope ceiling is the operator's approval.

Two behaviours are worth stating plainly:

* **A file that is gone withdraws its listing.** Deleting a manifest retires
  the listing instead of leaving a row nobody maintains. Withdrawn is not
  deleted — a guild that installed it keeps its instance and its provenance —
  and putting the file back publishes it again.
* **A bad file costs only itself.** One unreadable or invalid manifest is
  named in the log (and in the rescan response) and skipped; its neighbours
  publish and the boot continues.

Unset reads as an empty directory. Nothing is read and nothing is published,
and because the directory is the only source of operator listings, every one
still in the catalog is withdrawn — the same answer an empty directory gives.
A deployment that once had a directory (earlier releases copied one in for
every install) does not keep its listings forever after the setting goes away.
The scan reports ``configured=False`` all the same, and says nothing unless it
withdrew something.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.platform.marketplace import MarketplaceListing
from app.services.marketplace.catalog import (
    CatalogError,
    get_listing,
    get_listing_by_uid,
    published_uids,
    upsert_listing,
    withdraw_listing,
)

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_MANIFEST_BYTES",
    "MAX_MANIFEST_FILES",
    "MAX_PROBLEM_REASON",
    "OPERATOR_SOURCE",
    "OperatorCatalogScanRunning",
    "OperatorScanResult",
    "ScanProblem",
    "operator_catalog_dir",
    "scan_operator_catalog",
]

#: How the catalog records a listing that arrived this way.
OPERATOR_SOURCE = "operator"

#: Bound on one manifest. A listing is a document — artwork lives beside it as
#: a file, not inside it — so this is generous for anything honest and keeps a
#: single file from being read into memory unbounded.
MAX_MANIFEST_BYTES = 1_048_576  # 1 MiB

#: Bound on how many files one scan reads. Past this the directory is being
#: used for something other than a hand-maintained catalog, so the scan takes
#: the first ones in name order and says so rather than working without end.
MAX_MANIFEST_FILES = 500


class OperatorCatalogScanRunning(RuntimeError):
    """A scan is already in flight.

    Two scans over the same directory would interleave their upserts and their
    withdrawals, so the second is refused rather than queued: the answer it
    would give is the one already being computed.
    """


#: Bound on one reason. The problems are read as a list, so a single long
#: message must not crowd out the others; every validator message fits well
#: inside this.
MAX_PROBLEM_REASON = 300


@dataclass(frozen=True)
class ScanProblem:
    """One file the scan would not publish, and why.

    The file's name, never its path: an operator reads this to find the file
    they need to fix, and the name is what they mounted.
    """

    file: str
    reason: str

    def __post_init__(self) -> None:
        # Bounded here rather than at each call site, so every reason is short
        # enough to report however it was built.
        if len(self.reason) > MAX_PROBLEM_REASON:
            object.__setattr__(self, "reason", self.reason[:MAX_PROBLEM_REASON] + "…")


@dataclass(frozen=True)
class OperatorScanResult:
    """What one scan did."""

    #: Whether a directory is configured at all. False means nothing was read
    #: or published; ``withdrawn`` still counts the operator listings retired
    #: because no directory publishes them any more.
    configured: bool = False
    #: Configured, but the directory is not there to read.
    directory_missing: bool = False
    published: int = 0
    withdrawn: int = 0
    problems: tuple[ScanProblem, ...] = ()

    @property
    def skipped(self) -> int:
        return len(self.problems)


def operator_catalog_dir() -> Path | None:
    """The configured directory, or ``None`` when the feature is off."""
    configured = (settings.MARKETPLACE_EXTRA_CATALOG_DIR or "").strip()
    return Path(configured) if configured else None


# --- reading the directory --------------------------------------------------
#
# Filesystem work, kept synchronous and called through a worker thread. A
# mounted directory can be slow (a network volume) or large, and the scan runs
# during boot and from a request — neither may stall the event loop.


def _read_directory(
    root: Path,
) -> tuple[list[tuple[str, dict[str, Any]]], list[ScanProblem]]:
    """Every readable manifest in the directory, plus what could not be read.

    Sorted by filename so a re-scan touches rows in the same order every time,
    which keeps a failure reproducible rather than dependent on the filesystem.
    """
    manifests: list[tuple[str, dict[str, Any]]] = []
    problems: list[ScanProblem] = []

    try:
        paths = sorted(path for path in root.glob("*.json") if path.is_file())
    except OSError as exc:
        logger.warning("marketplace: cannot list the operator catalog: %s", exc)
        return [], [ScanProblem(file=root.name, reason="cannot be listed")]

    if len(paths) > MAX_MANIFEST_FILES:
        problems.append(
            ScanProblem(
                file=root.name,
                reason=(
                    f"holds more than {MAX_MANIFEST_FILES} manifests; "
                    f"reading the first {MAX_MANIFEST_FILES} by name"
                ),
            )
        )
        paths = paths[:MAX_MANIFEST_FILES]

    for path in paths:
        try:
            if path.stat().st_size > MAX_MANIFEST_BYTES:
                problems.append(
                    ScanProblem(
                        file=path.name,
                        reason=f"is larger than {MAX_MANIFEST_BYTES} bytes",
                    )
                )
                continue
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning(
                "marketplace: cannot read operator listing %s: %s", path, exc
            )
            problems.append(ScanProblem(file=path.name, reason="cannot be read"))
            continue
        except json.JSONDecodeError as exc:
            problems.append(
                ScanProblem(
                    file=path.name,
                    reason=(
                        f"is not valid JSON (line {exc.lineno}, column {exc.colno})"
                    ),
                )
            )
            continue
        if not isinstance(manifest, dict):
            problems.append(ScanProblem(file=path.name, reason="is not a JSON object"))
            continue
        manifests.append((path.name, manifest))

    return manifests, problems


# --- publishing -------------------------------------------------------------


async def _source_conflict(
    session: AsyncSession, manifest: dict[str, Any]
) -> str | None:
    """Why this manifest may not take a listing another source published.

    Both catalog identities are unique and neither is reassignable, so a
    manifest naming one that already belongs to a built-in or a registry
    listing is a collision to report rather than an update to apply. The
    catalog refuses a *reassignment* on its own; this is the case it would
    otherwise accept — same uid, same ``public_id``, different origin — where
    accepting means one source quietly replacing another's listing.
    """
    uid = str(manifest.get("uid", ""))
    public_id = str(manifest.get("public_id", ""))

    candidates: list[MarketplaceListing | None] = []
    if uid:
        candidates.append(await get_listing_by_uid(session, uid))
    if public_id:
        candidates.append(await get_listing(session, public_id))

    for existing in candidates:
        if existing is not None and existing.source != OPERATOR_SOURCE:
            return (
                f"{existing.public_id} (uid {existing.uid}) is already published "
                f"by the {existing.source} catalog"
            )
    return None


async def _withdraw_absent(session: AsyncSession, claimed: set[str]) -> int:
    """Retire the operator listings no file in the directory claims any more.

    The directory is the statement of what this deployment publishes, so a
    listing whose file is gone stops being offered. A file that is present but
    invalid still claims its uid, so a manifest with a mistake in it leaves the
    listing exactly as it was rather than pulling it while someone edits.

    Scope is every ``operator`` listing, because the directory is the only way
    one is published today. A second operator route without a backing file —
    an upload that is its own source of truth — has to be distinguishable here
    before it lands, or a scan would read it as removed.
    """
    rows = (
        await session.exec(
            select(MarketplaceListing).where(
                MarketplaceListing.source == OPERATOR_SOURCE,
                MarketplaceListing.available.is_(True),
            )
        )
    ).all()

    withdrawn = 0
    for row in rows:
        if row.uid in claimed:
            continue
        if await withdraw_listing(session, row.uid):
            withdrawn += 1
            logger.info(
                "marketplace: withdrew operator listing %s — no manifest publishes it",
                row.public_id,
            )
    return withdrawn


#: One scan at a time, process-wide. Checked and taken without an await in
#: between, so the check is decisive on a single event loop.
_scan_lock = asyncio.Lock()


async def scan_operator_catalog(
    session: AsyncSession, *, directory: Path | None = None
) -> OperatorScanResult:
    """Publish the directory's listings; retire the ones it no longer holds.

    The one code path: boot calls it, and so does the operator's rescan, so
    "I dropped a file in" needs no restart and answers exactly what a restart
    would have.

    Never raises for a bad manifest — the caller is either a boot that must
    continue or an operator who wants the whole picture — but does raise
    ``OperatorCatalogScanRunning`` when one is already under way. The caller
    commits.
    """
    root = directory or operator_catalog_dir()

    if _scan_lock.locked():
        raise OperatorCatalogScanRunning(
            "a marketplace catalog scan is already running"
        )
    async with _scan_lock:
        if root is None:
            return await _withdraw_without_directory(session)
        return await _scan(session, root)


async def _withdraw_without_directory(session: AsyncSession) -> OperatorScanResult:
    """No directory configured: retire every operator listing.

    The directory is the only source of operator listings, so with none set
    nothing publishes one, and the answer is the one an empty directory gives —
    every ``operator`` listing is withdrawn. Earlier releases copied a
    directory into every deployment; without this, a deployment that no longer
    has one would offer what it held forever. Withdrawn, not deleted, as on the
    configured path.
    """
    withdrawn = await _withdraw_absent(session, claimed=set())
    if withdrawn:
        logger.info(
            "marketplace: no operator catalog directory is set; "
            "withdrew %d operator listing(s)",
            withdrawn,
        )
    return OperatorScanResult(configured=False, withdrawn=withdrawn)


async def _scan(session: AsyncSession, root: Path) -> OperatorScanResult:
    if not await asyncio.to_thread(root.is_dir):
        # Configured but absent is worth saying out loud — an operator who
        # named a directory expects it to be read, and a typo'd mount would
        # otherwise look exactly like an empty catalog.
        logger.warning(
            "marketplace: operator catalog directory %s is not there; "
            "nothing published from it",
            root,
        )
        return OperatorScanResult(configured=True, directory_missing=True)

    manifests, problems = await asyncio.to_thread(_read_directory, root)

    published = 0
    # Every uid a file claims, whether or not it published — see _withdraw_absent.
    claimed: set[str] = set()
    for _, manifest in manifests:
        claimed |= published_uids(manifest)

    for filename, manifest in manifests:
        conflict = await _source_conflict(session, manifest)
        if conflict is not None:
            logger.warning(
                "marketplace: refusing operator listing %s: %s", filename, conflict
            )
            problems.append(ScanProblem(file=filename, reason=conflict))
            continue
        try:
            await upsert_listing(session, manifest, source=OPERATOR_SOURCE)
        except CatalogError as exc:
            logger.warning(
                "marketplace: skipping operator listing %s: %s", filename, exc
            )
            problems.append(ScanProblem(file=filename, reason=str(exc)))
            continue
        published += 1

    withdrawn = await _withdraw_absent(session, claimed)

    return OperatorScanResult(
        configured=True,
        published=published,
        withdrawn=withdrawn,
        problems=tuple(problems),
    )
