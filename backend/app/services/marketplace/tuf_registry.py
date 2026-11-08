"""The marketplace registry client: a TUF repository, verified here.

The registry is a TUF repository on a static host (python-tuf ``ngclient``).
This deployment trusts one root: the one shipped in the image at
``app/marketplace/root.json``, or the file ``MARKETPLACE_REGISTRY_ROOT`` names.
Everything else is verified from it. The host serving the files holds no key,
and nothing it serves is used until the metadata chain above it verifies.

**One refresh.**

1. Load the verified top-level metadata this deployment kept
   (``marketplace_tuf_metadata``) into a scratch directory, and hand it to an
   ``Updater`` bootstrapped from the trusted root. The client replays any root
   rotation from there and refuses a repository that is older than what it
   already verified, expired, or signed by keys the chain does not name.
2. Each delegation of the top-level ``targets`` role is a publisher, named by
   its prefix. The client cannot list a delegated role's targets, so each
   publisher's role is loaded by asking for a listing path under it that
   cannot exist, and its targets are read from the copy the client verified
   and kept. Every ``publishers/<prefix>/<uid>/listing.json`` found is then
   resolved again through the client's own delegation search, so a role only
   supplies paths its delegation covers.
3. Read each listing and the files it names into memory. Nothing is written to
   disk but metadata, and each file is checked against its target metadata
   before it is read.
4. Apply each listing in its own savepoint
   (:mod:`app.services.marketplace.registry_entries`), withdraw what the
   repository no longer lists, and store the metadata the client verified.
5. Under the root shipped in the image, read the terms the ``package`` role
   signs for each listing (:mod:`app.services.marketplace.package_terms`) and
   write them onto the listings. Under any other root every listing holds none.

The catalog moves as one transaction. A refusal of the repository itself
(unreachable, expired, not verifying) rolls it back and records the code on the
status row, so the last verified catalog stays exactly as it was.

**An uploaded bundle** (a tar of the repository's ``metadata/`` and
``targets/`` directories) goes through the same code with a fetcher that reads
the archive instead of the network.

**Not configured** means this build ships no trusted root yet: the shipped file
is a placeholder (a JSON object with a ``placeholder`` member). No worker runs
and the endpoints say so.

``session`` is a system-engine session throughout: the catalog, publishers and
registrations have no request-path writer.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import gzip
import hashlib
import io
import json
import logging
import tarfile
import tempfile
import zlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import parse

import httpx
from sqlalchemy import delete as sa_delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from tuf.api import exceptions as tuf_errors
from tuf.api.metadata import (
    DelegatedRole,
    Metadata,
    Root,
    Snapshot,
    Targets,
    Timestamp,
)
from tuf.ngclient import FetcherInterface, Updater, UpdaterConfig

from app.core.config import settings
from app.core.messages import MarketplaceRegistryMessages as Codes
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.models.platform.marketplace_registry import (
    STATUS_ROW_ID,
    MarketplaceRegistryStatus,
    MarketplaceTufMetadata,
)
from app.services.marketplace import package_terms, registry_entries
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.services.marketplace.registry_entries import RegistryError
from app.services.platform import app_settings as app_settings_service
from app.services.safe_http import ResponseTooLargeError, request_public_target
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BUILTIN_ROOT_PATH",
    "BUNDLE_SOURCE",
    "RefreshResult",
    "RegistryError",
    "RegistryStatus",
    "SkippedEntry",
    "TrustAnchor",
    "apply_bundle",
    "configured_root_is_builtin",
    "load_trust_anchor",
    "process_registry_refresh",
    "read_bundle",
    "read_status",
    "refresh_registry",
    "registry_available",
    "registry_base_url",
]

#: The trusted root this build ships.
BUILTIN_ROOT_PATH = Path(__file__).resolve().parents[2] / "marketplace" / "root.json"

#: The member a placeholder root file carries instead of TUF metadata.
PLACEHOLDER_KEY = "placeholder"

#: What the status row records as the source of an uploaded bundle.
BUNDLE_SOURCE = "bundle"

#: The base URL a bundle's files are addressed under. Never fetched: the
#: bundle fetcher answers every request from the archive.
BUNDLE_BASE_URL = "https://bundle.invalid/"

#: Metadata files are small; a root is a handful of keys, a delegated role a
#: few hundred target entries.
MAX_METADATA_BYTES = 1024 * 1024
MAX_TIMESTAMP_BYTES = 16 * 1024

#: The most one response may carry, whatever it is. Every file has a tighter
#: cap from its metadata or its kind; this bounds a response before either is
#: known.
MAX_FETCH_BYTES = 2 * 1024 * 1024

#: Per-request budget for one fetch.
FETCH_TIMEOUT_SECONDS = 15.0

#: An uploaded bundle: the archive as uploaded, the tar inside it once
#: decompressed, and the files in it.
MAX_BUNDLE_BYTES = 32 * 1024 * 1024
MAX_BUNDLE_UNPACKED_BYTES = 64 * 1024 * 1024
MAX_BUNDLE_FILES = 5000

_GZIP_MAGIC = b"\x1f\x8b"

#: How many listings one repository may carry.
MAX_LISTINGS = 500

_UPDATER_CONFIG = UpdaterConfig(
    max_root_rotations=32,
    max_delegations=64,
    root_max_length=MAX_METADATA_BYTES,
    timestamp_max_length=MAX_TIMESTAMP_BYTES,
    snapshot_max_length=MAX_METADATA_BYTES,
    targets_max_length=MAX_METADATA_BYTES,
)

#: The directories a repository keeps its metadata and target files in.
_METADATA_DIR = "metadata/"
_TARGETS_DIR = "targets/"
_ROOT_HISTORY = "root_history"

#: The top-level roles whose verified copies are kept between refreshes. A
#: publisher's role is fetched fresh each time the snapshot moves, so the only
#: copy of one read here is the one the client verified in this refresh.
_KEPT_ROLES = (Timestamp.type, Snapshot.type, Targets.type)

#: The uid half of a probe path: never a uid, so the probe names no target.
_PROBE_UID = "_"


# --- the trusted root ---------------------------------------------------------


@dataclass(frozen=True)
class TrustAnchor:
    """The root this deployment trusts, as bytes."""

    data: bytes
    digest: str
    #: Whether it is the root shipped in the image.
    builtin: bool
    version: int


def _read_root_file(path: Path) -> bytes | None:
    """The root file's bytes, or ``None`` when it is the placeholder."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise RegistryError(Codes.ROOT_INVALID, f"{path}: {exc}") from exc
    if len(data) > MAX_METADATA_BYTES:
        raise RegistryError(Codes.ROOT_INVALID, f"{path} is too large")
    try:
        document = json.loads(data)
    except ValueError as exc:
        raise RegistryError(Codes.ROOT_INVALID, f"{path} is not JSON") from exc
    if (
        isinstance(document, dict)
        and PLACEHOLDER_KEY in document
        and "signed" not in document
    ):
        return None
    return data


def _root_version(data: bytes) -> int:
    try:
        metadata = Metadata.from_bytes(data)
    except tuf_errors.RepositoryError as exc:
        raise RegistryError(Codes.ROOT_INVALID, f"not TUF metadata: {exc}") from exc
    if not isinstance(metadata.signed, Root):
        raise RegistryError(Codes.ROOT_INVALID, "not root metadata")
    return metadata.signed.version


def load_trust_anchor() -> TrustAnchor | None:
    """The trusted root, or ``None`` when this build has none yet.

    ``MARKETPLACE_REGISTRY_ROOT`` replaces the shipped root. The result is
    ``builtin`` only when the root in use is byte for byte the shipped one.
    """
    builtin_data: bytes | None = None
    if BUILTIN_ROOT_PATH.is_file():
        builtin_data = _read_root_file(BUILTIN_ROOT_PATH)

    override = (settings.MARKETPLACE_REGISTRY_ROOT or "").strip()
    data = _read_root_file(Path(override)) if override else builtin_data
    if data is None:
        return None
    digest = hashlib.sha256(data).hexdigest()
    builtin = (
        builtin_data is not None and digest == hashlib.sha256(builtin_data).hexdigest()
    )
    return TrustAnchor(
        data=data, digest=digest, builtin=builtin, version=_root_version(data)
    )


def registry_available() -> bool:
    """Whether this build has a trusted root to follow a registry with."""
    try:
        return load_trust_anchor() is not None
    except RegistryError:
        # A root that is present but unreadable is a configuration problem
        # the refresh reports, not an absent feature.
        return True


def configured_root_is_builtin() -> bool:
    """Whether the root in use is the one shipped in the image."""
    try:
        anchor = load_trust_anchor()
    except RegistryError:
        return False
    return anchor is not None and anchor.builtin


def registry_base_url() -> str:
    url = (settings.MARKETPLACE_REGISTRY_URL or "").strip()
    return url if url.endswith("/") else f"{url}/"


# --- fetchers -----------------------------------------------------------------

_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = httpx.URL(url)
    return (
        parsed.scheme,
        parsed.host,
        parsed.port or _DEFAULT_PORTS.get(parsed.scheme),
    )


def _request_headers(url: str) -> dict[str, str]:
    """The headers for a fetch of ``url``: the configured token goes only to
    the registry URL's own origin."""
    headers = {"Accept": "application/json, */*"}
    token = (settings.MARKETPLACE_REGISTRY_TOKEN or "").strip()
    if token and _origin(url) == _origin(registry_base_url()):
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _get(url: str) -> bytes:
    """GET ``url`` through the shared egress layer.

    The layer resolves the host once, connects to the address it validated,
    follows no redirect, and caps the body.
    """
    try:
        response = await request_public_target(
            "GET",
            url,
            headers=_request_headers(url),
            timeout=httpx.Timeout(FETCH_TIMEOUT_SECONDS),
            max_bytes=MAX_FETCH_BYTES,
        )
    except ResponseTooLargeError as exc:
        raise tuf_errors.DownloadLengthMismatchError(
            f"{url} is larger than {MAX_FETCH_BYTES} bytes"
        ) from exc
    except (
        httpx.HTTPError,
        WebhookTargetUrlError,
        WebhookTargetUrlPrivateError,
    ) as exc:
        raise tuf_errors.DownloadError(f"{url}: {exc}") from exc
    if response.status_code != 200:
        raise tuf_errors.DownloadHTTPError(
            f"{url} returned {response.status_code}", response.status_code
        )
    return response.content


class SafeHttpFetcher(FetcherInterface):
    """Fetches for a TUF client running in a worker thread.

    The client is synchronous; the egress helper is async. Each fetch is
    scheduled on the event loop that started the refresh, and the worker
    thread waits for it.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _fetch(self, url: str) -> Iterator[bytes]:
        future = asyncio.run_coroutine_threadsafe(_get(url), self._loop)
        try:
            body = future.result(timeout=FETCH_TIMEOUT_SECONDS * 2)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise tuf_errors.SlowRetrievalError(f"{url} timed out") from exc
        return iter((body,))


class BundleFetcher(FetcherInterface):
    """Answers a TUF client's fetches from an uploaded archive."""

    def __init__(self, files: Mapping[str, bytes]) -> None:
        self._files = files

    def _fetch(self, url: str) -> Iterator[bytes]:
        if not url.startswith(BUNDLE_BASE_URL):
            raise tuf_errors.DownloadHTTPError(f"{url} is not in the bundle", 404)
        name = parse.unquote(url[len(BUNDLE_BASE_URL) :])
        data = self._files.get(name)
        if data is None:
            raise tuf_errors.DownloadHTTPError(f"{name} is not in the bundle", 404)
        return iter((data,))


def _bundle_name(raw: str) -> str | None:
    """A member name as the bundle fetcher looks it up, or ``None`` for one
    that is not a plain relative path."""
    name = raw.removeprefix("./")
    if not name or name.startswith("/") or "\\" in name:
        return None
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    return name


def read_bundle(archive: bytes) -> dict[str, bytes]:
    """The files of an uploaded bundle, by path under the repository root.

    The archive is a tar, or a gzipped tar, of a repository's ``metadata/``
    and ``targets/`` directories, at its top level or inside one top
    directory. It is decompressed into memory up to a fixed size, and only
    regular files are read from it; nothing is extracted to disk.
    """
    if len(archive) > MAX_BUNDLE_BYTES:
        raise RegistryError(Codes.BUNDLE_INVALID, "the bundle is too large")
    tar_bytes = archive
    if archive.startswith(_GZIP_MAGIC):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(archive)) as unpacked:
                tar_bytes = unpacked.read(MAX_BUNDLE_UNPACKED_BYTES + 1)
        except (OSError, EOFError, zlib.error) as exc:
            raise RegistryError(Codes.BUNDLE_INVALID, f"not gzip: {exc}") from exc
        if len(tar_bytes) > MAX_BUNDLE_UNPACKED_BYTES:
            raise RegistryError(Codes.BUNDLE_INVALID, "the bundle is too large")
    files: dict[str, bytes] = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
            for member in tar:
                if not member.isreg():
                    continue
                if len(files) >= MAX_BUNDLE_FILES:
                    raise RegistryError(
                        Codes.BUNDLE_INVALID, "the bundle holds too many files"
                    )
                name = _bundle_name(member.name)
                if name is None:
                    raise RegistryError(
                        Codes.BUNDLE_INVALID, f"{member.name!r} is not a plain path"
                    )
                if member.size > MAX_FETCH_BYTES:
                    raise RegistryError(
                        Codes.BUNDLE_INVALID, f"{name} is larger than a registry file"
                    )
                total += member.size
                if total > MAX_BUNDLE_BYTES:
                    raise RegistryError(Codes.BUNDLE_INVALID, "the bundle is too large")
                handle = tar.extractfile(member)
                if handle is None:
                    continue
                files[name] = handle.read(MAX_FETCH_BYTES + 1)
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise RegistryError(Codes.BUNDLE_INVALID, f"not a tar archive: {exc}") from exc

    if not any(name.startswith(_METADATA_DIR) for name in files):
        # One top directory around the repository, as `tar czf x.tgz public/`
        # writes it.
        tops = {name.split("/", 1)[0] for name in files}
        if len(tops) == 1:
            top = f"{tops.pop()}/"
            files = {name[len(top) :]: data for name, data in files.items()}
    if not any(name.startswith(_METADATA_DIR) for name in files):
        raise RegistryError(Codes.BUNDLE_INVALID, "the bundle has no metadata/")
    return {
        name: data
        for name, data in files.items()
        if name.startswith((_METADATA_DIR, _TARGETS_DIR))
    }


# --- the verified repository --------------------------------------------------


@dataclass(frozen=True)
class StoredFile:
    """One metadata file, as ``marketplace_tuf_metadata`` holds it."""

    role: str
    version: int
    data: bytes


@dataclass(frozen=True)
class RepositoryFacts:
    """What the verified top-level metadata says."""

    root_version: int
    snapshot_version: int
    expires_at: datetime
    consistent_snapshot: bool


def _metadata_filename(role: str) -> str:
    return f"{parse.quote(role, '')}.json"


def _tuf_code(exc: BaseException) -> str:
    if isinstance(exc, tuf_errors.ExpiredMetadataError):
        return Codes.EXPIRED
    if isinstance(exc, tuf_errors.DownloadLengthMismatchError):
        return Codes.METADATA_REJECTED
    if isinstance(exc, tuf_errors.DownloadError):
        return Codes.UNREACHABLE
    return Codes.METADATA_REJECTED


class VerifiedRepository:
    """One TUF client over a scratch directory.

    Every method runs in a worker thread (``asyncio.to_thread``), one at a
    time. The directory holds metadata only.
    """

    def __init__(
        self,
        workdir: Path,
        anchor: TrustAnchor,
        stored: Sequence[StoredFile],
        base_url: str,
        fetcher: FetcherInterface,
    ) -> None:
        self._workdir = workdir
        self._fetcher = fetcher
        self._targets_base = base_url + _TARGETS_DIR
        self._restore(anchor, stored)
        try:
            self._updater = Updater(
                str(workdir),
                base_url + _METADATA_DIR,
                None,
                self._targets_base,
                fetcher,
                _UPDATER_CONFIG,
                bootstrap=anchor.data,
            )
        except (tuf_errors.RepositoryError, ValueError) as exc:
            raise RegistryError(Codes.ROOT_INVALID, str(exc)) from exc
        self._walked: set[str] = set()
        #: Delegations whose metadata did not load this time, with the code
        #: naming why: what they cover is unknown, not gone.
        self.failed: list[tuple[DelegatedRole, str]] = []
        self._facts: RepositoryFacts | None = None

    def _restore(self, anchor: TrustAnchor, stored: Sequence[StoredFile]) -> None:
        history = self._workdir / _ROOT_HISTORY
        history.mkdir(parents=True, exist_ok=True)
        for item in stored:
            if item.role == Root.type:
                # The chain is replayed from the trusted root; anything older
                # than it is not part of it.
                if item.version > anchor.version:
                    (history / f"{item.version}.root.json").write_bytes(item.data)
            elif item.role in _KEPT_ROLES:
                (self._workdir / _metadata_filename(item.role)).write_bytes(item.data)

    def refresh(self) -> RepositoryFacts:
        """Update the top-level metadata. Raises ``RegistryError``."""
        try:
            self._updater.refresh()
        except (tuf_errors.RepositoryError, tuf_errors.DownloadError) as exc:
            raise RegistryError(_tuf_code(exc), str(exc)) from exc
        root = self._read(_metadata_filename(Root.type), Root)
        snapshot = self._read(_metadata_filename(Snapshot.type), Snapshot)
        timestamp = self._read(_metadata_filename(Timestamp.type), Timestamp)
        self._facts = RepositoryFacts(
            root_version=root.version,
            snapshot_version=snapshot.version,
            expires_at=timestamp.expires,
            consistent_snapshot=bool(root.consistent_snapshot),
        )
        return self._facts

    def _read(self, filename: str, kind: type) -> Any:
        """A verified top-level file the client kept. Read only after a
        successful refresh, when each one is the copy it verified."""
        signed = Metadata.from_bytes((self._workdir / filename).read_bytes()).signed
        if not isinstance(signed, kind):
            raise RegistryError(Codes.METADATA_REJECTED, f"{filename} is not {kind}")
        return signed

    def _kept_targets(self, role: str) -> Targets:
        """A targets role the client verified and kept in this refresh."""
        return self._read(_metadata_filename(role), Targets)

    def listing_paths(self) -> list[str]:
        """Every listing path a publisher's role signs.

        A publisher whose role does not load is recorded in :attr:`failed` and
        skipped: what it covers is unknown this time, not withdrawn.
        """
        top = self._kept_targets(Targets.type)
        delegations = top.delegations
        roles = (
            list(delegations.roles.values())
            if delegations is not None and delegations.roles
            else []
        )
        if len(roles) > _UPDATER_CONFIG.max_delegations:
            raise RegistryError(
                Codes.METADATA_REJECTED, "the repository delegates too many roles"
            )
        found: set[str] = set()
        for role in roles:
            prefix = role.name
            probe = registry_entries.listing_path(prefix, _PROBE_UID)
            if prefix == package_terms.PACKAGE_ROLE and not role.is_delegated_path(
                probe
            ):
                # The package's role, read by :meth:`package_role`.
                continue
            if registry_entries.parse_prefix(
                prefix
            ) is None or not role.is_delegated_path(probe):
                logger.warning(
                    "marketplace registry: delegation %r is not a publisher", prefix
                )
                continue
            try:
                self._updater.get_targetinfo(probe)
                delegated = self._kept_targets(prefix)
            except (
                tuf_errors.RepositoryError,
                tuf_errors.DownloadError,
                OSError,
            ) as exc:
                logger.warning(
                    "marketplace registry: publisher %s did not load: %s", prefix, exc
                )
                self.failed.append((role, _tuf_code(exc)))
                continue
            self._walked.add(prefix)
            for path in delegated.targets:
                parsed = registry_entries.parse_listing_path(path)
                if parsed is not None and parsed.prefix == prefix:
                    found.add(path)
        if len(found) > MAX_LISTINGS:
            raise RegistryError(
                Codes.METADATA_REJECTED,
                f"the repository lists {len(found)} listings, more than {MAX_LISTINGS}",
            )
        return sorted(found)

    def package_role(self) -> tuple[DelegatedRole, Targets] | None:
        """The ``package`` delegation and the targets it signs, or ``None``
        when the repository carries no package role file.

        A repository may delegate the role and publish no file for it, as the
        public index does: that is no terms, not a failure. A role file the
        snapshot lists that does not verify raises ``RegistryError``.
        """
        top = self._kept_targets(Targets.type)
        delegations = top.delegations
        role = (
            delegations.roles.get(package_terms.PACKAGE_ROLE)
            if delegations is not None and delegations.roles
            else None
        )
        probe = package_terms.terms_path(_PROBE_UID)
        if role is None or not role.is_delegated_path(probe):
            return None
        snapshot = self._read(_metadata_filename(Snapshot.type), Snapshot)
        if f"{role.name}.json" not in snapshot.meta:
            return None
        try:
            self._updater.get_targetinfo(probe)
            return role, self._kept_targets(role.name)
        except (
            tuf_errors.RepositoryError,
            tuf_errors.DownloadError,
            OSError,
        ) as exc:
            raise RegistryError(
                _tuf_code(exc), f"the package role did not load: {exc}"
            ) from exc

    def package_terms(
        self, role: DelegatedRole, targets: Targets, uid: str
    ) -> bytes | None:
        """The terms file the package role signs for listing ``uid``, or
        ``None`` when it signs none. Read from that role alone."""
        path = package_terms.terms_path(uid)
        if not role.is_delegated_path(path):
            return None
        info = targets.targets.get(path)
        if info is None:
            return None
        return self._download(info, package_terms.MAX_TERMS_BYTES)

    def uncertain(self, path: str) -> bool:
        """Whether ``path`` is covered by a delegation that did not load."""
        return any(role.is_delegated_path(path) for role, _ in self.failed)

    def resolves(self, path: str) -> bool:
        """Whether the client's own delegation search finds ``path``."""
        try:
            return self._updater.get_targetinfo(path) is not None
        except (tuf_errors.RepositoryError, tuf_errors.DownloadError):
            return False

    def fetch_target(self, path: str, max_bytes: int) -> bytes:
        """A target file's bytes, checked against its metadata, in memory."""
        try:
            info = self._updater.get_targetinfo(path)
        except (tuf_errors.RepositoryError, tuf_errors.DownloadError) as exc:
            raise RegistryError(Codes.TARGET_REJECTED, f"{path}: {exc}") from exc
        if info is None:
            raise RegistryError(Codes.TARGET_REJECTED, f"{path} is not listed")
        return self._download(info, max_bytes)

    def top_level_target(self, path: str, max_bytes: int) -> bytes | None:
        """A file the top-level ``targets`` role lists itself, or ``None``."""
        info = self._kept_targets(Targets.type).targets.get(path)
        if info is None:
            return None
        return self._download(info, max_bytes)

    def _download(self, info: Any, max_bytes: int) -> bytes:
        if info.length > max_bytes:
            raise RegistryError(
                Codes.TARGET_REJECTED, f"{info.path} is larger than {max_bytes} bytes"
            )
        target_path = info.path
        if (
            self._facts is not None
            and self._facts.consistent_snapshot
            and _UPDATER_CONFIG.prefix_targets_with_hash
        ):
            digest = next(iter(info.hashes.values()))
            directory, sep, basename = target_path.rpartition("/")
            target_path = f"{directory}{sep}{digest}.{basename}"
        try:
            data = self._fetcher.download_bytes(
                self._targets_base + target_path, info.length
            )
            info.verify_length_and_hashes(data)
        except (tuf_errors.DownloadError, tuf_errors.RepositoryError) as exc:
            raise RegistryError(Codes.TARGET_REJECTED, f"{info.path}: {exc}") from exc
        return data

    def verified_files(self) -> list[StoredFile]:
        """The top-level metadata the client verified this time, to keep."""
        files: list[StoredFile] = []
        for path in sorted((self._workdir / _ROOT_HISTORY).glob("*.root.json")):
            data = path.read_bytes()
            files.append(
                StoredFile(
                    role=Root.type,
                    version=Metadata.from_bytes(data).signed.version,
                    data=data,
                )
            )
        for role in _KEPT_ROLES:
            path = self._workdir / _metadata_filename(role)
            if not path.is_file():
                continue
            data = path.read_bytes()
            files.append(
                StoredFile(
                    role=role,
                    version=Metadata.from_bytes(data).signed.version,
                    data=data,
                )
            )
        return files


# --- state ---------------------------------------------------------------------


async def _status_row(session: AsyncSession) -> MarketplaceRegistryStatus:
    row = await session.get(MarketplaceRegistryStatus, STATUS_ROW_ID)
    if row is None:
        row = MarketplaceRegistryStatus(id=STATUS_ROW_ID)
        session.add(row)
        await session.flush()
    return row


async def _stored_files(session: AsyncSession) -> list[StoredFile]:
    rows = (await session.exec(select(MarketplaceTufMetadata))).all()
    return [StoredFile(role=r.role, version=r.version, data=r.data) for r in rows]


async def _keep_files(
    session: AsyncSession, files: Sequence[StoredFile], *, now: datetime
) -> None:
    """Store what the client verified, replacing each role's older copy.

    Every root version is kept, so the chain replays from the trusted root.
    """
    stored = {(r.role, r.version): r for r in await _stored_rows(session)}
    current = {(f.role, f.version) for f in files}
    for (role, version), row in stored.items():
        if role != Root.type and (role, version) not in current:
            await session.delete(row)
    for item in files:
        row = stored.get((item.role, item.version))
        if row is None:
            session.add(
                MarketplaceTufMetadata(
                    role=item.role, version=item.version, data=item.data, updated_at=now
                )
            )
        elif row.data != item.data:
            row.data = item.data
            row.updated_at = now
            session.add(row)
    await session.flush()


async def _stored_rows(session: AsyncSession) -> Sequence[MarketplaceTufMetadata]:
    return (await session.exec(select(MarketplaceTufMetadata))).all()


async def _claim_refresh(session: AsyncSession) -> bool:
    """Take the cross-process refresh lock for this transaction."""
    return await advisory_lock(session, LockNamespace.MARKETPLACE_REFRESH, wait=False)


# --- the refresh ------------------------------------------------------------------


@dataclass(frozen=True)
class SkippedEntry:
    """A listing (or a delegated role) the repository carried that did not land."""

    name: str
    code: str


@dataclass
class RefreshResult:
    """What one refresh or bundle upload did."""

    #: Whether it ran (false when disabled, not configured, or already running).
    ran: bool
    #: The refusal that stopped it, or ``None`` when it applied.
    code: str | None = None
    root_version: int | None = None
    upserted: int = 0
    withdrawn: int = 0
    #: The repository had not changed since the last clean refresh.
    unchanged: bool = False
    skipped: list[SkippedEntry] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.ran and self.code is None


#: One refresh at a time in this process; the advisory lock covers replicas.
_refresh_lock = asyncio.Lock()


async def _apply(
    session: AsyncSession,
    *,
    anchor: TrustAnchor,
    base_url: str,
    source: str,
    fetcher: FetcherInterface,
    force: bool,
    now: datetime,
) -> RefreshResult:
    if not await _claim_refresh(session):
        return RefreshResult(ran=False, code=Codes.REFRESH_IN_PROGRESS)

    status = await _status_row(session)
    if status.root_sha256 == anchor.digest:
        stored = await _stored_files(session)
    else:
        # Metadata verified under another root is not part of this chain.
        await session.exec(sa_delete(MarketplaceTufMetadata))
        stored = []

    with tempfile.TemporaryDirectory(prefix="initiative-tuf-") as scratch:
        repo = await asyncio.to_thread(
            VerifiedRepository, Path(scratch), anchor, stored, base_url, fetcher
        )
        facts = await asyncio.to_thread(repo.refresh)

        unchanged = (
            not force
            and status.root_sha256 == anchor.digest
            and status.snapshot_version == facts.snapshot_version
            and status.last_error is None
        )
        result = RefreshResult(ran=True, root_version=facts.root_version)
        if unchanged:
            if not anchor.builtin:
                # The same repository, trusted under another root than the
                # shipped one: none of its terms hold here.
                await package_terms.apply_terms(session, {})
            files = await asyncio.to_thread(repo.verified_files)
            await _keep_files(session, files, now=now)
            _record_attempt(status, anchor, facts, source=source, now=now)
            status.last_success_at = now
            session.add(status)
            result.unchanged = True
            return result

        paths = await asyncio.to_thread(repo.listing_paths)
        for failed, code in repo.failed:
            result.skipped.append(SkippedEntry(name=failed.name, code=code))

        async def fetch(path: str, max_bytes: int) -> bytes:
            return await asyncio.to_thread(repo.fetch_target, path, max_bytes)

        async def publisher_record(prefix: str) -> bytes | None:
            return await asyncio.to_thread(
                repo.top_level_target,
                registry_entries.publisher_record_path(prefix),
                registry_entries.MAX_PUBLISHER_RECORD_BYTES,
            )

        context = registry_entries.EntryContext(
            fetch=fetch,
            publisher_record=publisher_record,
            now=now,
        )
        present: set[str] = set()
        for path in paths:
            parsed = registry_entries.parse_listing_path(path)
            if parsed is None:  # pragma: no cover - filtered by listing_paths
                continue
            if not await asyncio.to_thread(repo.resolves, path):
                # A role listed a path outside its delegation.
                continue
            # Recorded whatever happens next: a listing the repository still
            # carries is not withdrawn because this deployment could not take
            # it this time.
            present.add(parsed.uid)
            try:
                async with session.begin_nested():
                    await registry_entries.apply_entry(session, path, context)
                result.upserted += 1
            except registry_entries.UnsupportedEntry as exc:
                logger.info("marketplace registry: not carried here: %s", exc)
            except RegistryError as exc:
                logger.warning(
                    "marketplace registry: skipping %s (%s): %s",
                    path,
                    exc.code,
                    exc.detail,
                )
                result.skipped.append(SkippedEntry(name=path, code=exc.code))

        result.withdrawn = await registry_entries.withdraw_missing(
            session, present=present, uncertain=repo.uncertain, now=now
        )
        if anchor.builtin:
            terms, keep = await _read_terms(repo, present, result)
        else:
            terms, keep = {}, set()
        await package_terms.apply_terms(
            session, terms, keep=keep, uncertain=repo.uncertain
        )
        files = await asyncio.to_thread(repo.verified_files)
        await _keep_files(session, files, now=now)

    _record_attempt(status, anchor, facts, source=source, now=now)
    status.listing_count = len(present)
    # A skipped listing leaves the run incomplete, which is also what makes the
    # next refresh read the same snapshot again rather than treat it as done.
    status.last_error = result.skipped[0].code if result.skipped else None
    if not result.skipped:
        status.last_success_at = now
    session.add(status)
    return result


async def _read_terms(
    repo: VerifiedRepository, present: set[str], result: RefreshResult
) -> tuple[dict[str, package_terms.ListingTerms], set[str] | None]:
    """The package's terms for each listing present, and the uids whose
    terms could not be read and so stay as they are (``None`` for every one,
    when the package role itself did not load)."""
    try:
        package = await asyncio.to_thread(repo.package_role)
    except RegistryError as exc:
        logger.warning(
            "marketplace registry: package terms not read (%s): %s",
            exc.code,
            exc.detail,
        )
        result.skipped.append(
            SkippedEntry(name=package_terms.PACKAGE_ROLE, code=exc.code)
        )
        return {}, None
    if package is None:
        return {}, set()
    role, targets = package
    terms: dict[str, package_terms.ListingTerms] = {}
    keep: set[str] = set()
    for uid in sorted(present):
        try:
            raw = await asyncio.to_thread(repo.package_terms, role, targets, uid)
            if raw is not None:
                terms[uid] = package_terms.parse_terms(raw, uid=uid)
        except RegistryError as exc:
            logger.warning(
                "marketplace registry: terms for %s refused (%s): %s",
                uid,
                exc.code,
                exc.detail,
            )
            result.skipped.append(
                SkippedEntry(name=package_terms.terms_path(uid), code=exc.code)
            )
            keep.add(uid)
    return terms, keep


def _record_attempt(
    status: MarketplaceRegistryStatus,
    anchor: TrustAnchor,
    facts: RepositoryFacts,
    *,
    source: str,
    now: datetime,
) -> None:
    """What a verified repository says, on the status row."""
    status.root_sha256 = anchor.digest
    status.root_version = facts.root_version
    status.snapshot_version = facts.snapshot_version
    status.expires_at = facts.expires_at
    status.source = source[:2000]
    status.last_attempt_at = now
    status.last_error = None
    status.updated_at = now


async def _record_failure(
    session: AsyncSession, *, code: str, source: str, now: datetime
) -> None:
    """Note a refusal on the status row, leaving the catalog untouched.

    Runs after the refresh transaction was rolled back.
    """
    try:
        status = await _status_row(session)
        status.last_attempt_at = now
        status.last_error = code
        status.source = source[:2000]
        status.updated_at = now
        session.add(status)
        await session.commit()
    except Exception:  # pragma: no cover - bookkeeping must not mask the refusal
        await session.rollback()
        logger.exception("marketplace registry: could not record the failed refresh")


async def _run(
    session: AsyncSession,
    *,
    base_url: str,
    source: str,
    fetcher_for: Callable[[], FetcherInterface],
    force: bool,
) -> RefreshResult:
    now = datetime.now(UTC)
    try:
        anchor = load_trust_anchor()
    except RegistryError as exc:
        logger.warning("marketplace registry: %s (%s)", exc.code, exc.detail)
        await _record_failure(session, code=exc.code, source=source, now=now)
        return RefreshResult(ran=True, code=exc.code)
    if anchor is None:
        return RefreshResult(ran=False, code=Codes.NOT_CONFIGURED)

    if _refresh_lock.locked():
        return RefreshResult(ran=False, code=Codes.REFRESH_IN_PROGRESS)
    async with _refresh_lock:
        try:
            result = await _apply(
                session,
                anchor=anchor,
                base_url=base_url,
                source=source,
                fetcher=fetcher_for(),
                force=force,
                now=now,
            )
        except RegistryError as exc:
            await session.rollback()
            logger.warning(
                "marketplace registry: refused (%s): %s", exc.code, exc.detail
            )
            await _record_failure(session, code=exc.code, source=source, now=now)
            return RefreshResult(ran=True, code=exc.code)
        except Exception:
            await session.rollback()
            raise
        await session.commit()
    invalidate_registrations()
    return result


async def refresh_registry(
    session: AsyncSession,
    *,
    force: bool = False,
    fetcher: FetcherInterface | None = None,
) -> RefreshResult:
    """Fetch, verify and apply the registry, when the platform switch is on.

    ``force`` re-applies a repository that has not changed since the last
    clean refresh (the operator's "refresh now"). It does not reach the
    verification: an expired or rolled-back repository is refused either way.
    ``fetcher`` replaces the network, for tests.
    """
    if not await app_settings_service.marketplace_registry_enabled(session):
        await session.rollback()
        return RefreshResult(ran=False, code=Codes.DISABLED)
    await session.rollback()
    loop = asyncio.get_running_loop()
    base_url = registry_base_url()
    return await _run(
        session,
        base_url=base_url,
        source=base_url,
        fetcher_for=lambda: fetcher or SafeHttpFetcher(loop),
        force=force,
    )


async def apply_bundle(session: AsyncSession, archive: bytes) -> RefreshResult:
    """Verify and apply an uploaded bundle, exactly as a fetched repository.

    Applies whether or not the platform switch is on: a deployment that cannot
    reach the registry turns the switch off and uploads bundles instead.
    """
    files = read_bundle(archive)
    return await _run(
        session,
        base_url=BUNDLE_BASE_URL,
        source=BUNDLE_SOURCE,
        fetcher_for=lambda: BundleFetcher(files),
        force=True,
    )


# --- reading the state ---------------------------------------------------------


@dataclass(frozen=True)
class RegistryStatus:
    """Where this deployment stands with its registry, for the operator."""

    enabled: bool
    configured: bool
    custom_root: bool
    registry_url: str
    root_version: int | None
    expires_at: datetime | None
    source: str | None
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    listing_count: int


async def read_status(session: AsyncSession, *, enabled: bool) -> RegistryStatus:
    """The status row and the configuration it is read against."""
    try:
        anchor = load_trust_anchor()
        root_error: str | None = None
    except RegistryError as exc:
        anchor = None
        root_error = exc.code
    row = await session.get(MarketplaceRegistryStatus, STATUS_ROW_ID)
    current = (
        row is not None and anchor is not None and row.root_sha256 == anchor.digest
    )
    return RegistryStatus(
        enabled=enabled,
        configured=anchor is not None or root_error is not None,
        custom_root=anchor is not None and not anchor.builtin,
        registry_url=registry_base_url(),
        root_version=row.root_version if row is not None and current else None,
        expires_at=row.expires_at if row is not None and current else None,
        source=row.source if row is not None else None,
        last_attempt_at=row.last_attempt_at if row is not None else None,
        last_success_at=row.last_success_at if row is not None and current else None,
        last_error=root_error or (row.last_error if row is not None else None),
        listing_count=row.listing_count if row is not None else 0,
    )


async def process_registry_refresh() -> None:
    """The background refresh, on its own system-engine session."""
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as session:
        result = await refresh_registry(session)
    if result.ok and not result.unchanged:
        logger.info(
            "marketplace registry: root %s applied — %d listing(s), %d withdrawn",
            result.root_version,
            result.upserted,
            result.withdrawn,
        )
