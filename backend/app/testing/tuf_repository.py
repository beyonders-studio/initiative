"""A TUF registry repository built in memory, for tests.

Laid out the way the registry builder lays one out: consistent snapshots
(``<version>.<role>.json`` metadata, targets served under their sha256), one
delegated role per publisher with the three terminating patterns, and each
publisher's record as a target of the top-level ``targets`` role. A repository
may also delegate the ``package`` role over ``entitlements/*`` and ``grants/*``,
with or without publishing a role file for it, as a package and the public
index do. Every key is generated per repository and lives only in memory.

The files are served by :class:`RepositoryFetcher`, which records every URL it
was asked for.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from securesystemslib.signer import CryptoSigner
from tuf.api import exceptions as tuf_errors
from tuf.api.metadata import (
    DelegatedRole,
    Delegations,
    Metadata,
    MetaFile,
    Root,
    Snapshot,
    TargetFile,
    Targets,
    Timestamp,
)
from tuf.ngclient import FetcherInterface

__all__ = [
    "BASE_URL",
    "RepositoryFetcher",
    "TufRepository",
    "container_registration",
    "dashboard_definition",
    "png",
    "service_plugin_definition",
]

#: Where the fake repository is served from.
BASE_URL = "https://registry.test/public/"

_TOP_LEVEL = ("root", "targets", "snapshot", "timestamp")


def png(seed: str) -> bytes:
    """Bytes that begin like a PNG, distinct per seed."""
    return b"\x89PNG\r\n\x1a\n" + seed.encode()


def service_plugin_definition(public_id: str) -> dict[str, Any]:
    return {
        "plugin_kind": "service",
        "service": {"public_id": public_id},
        "features": [],
    }


def dashboard_definition() -> dict[str, Any]:
    return {
        "widgets": [
            {
                "id": "w1",
                "type": "stat",
                "binding": {
                    "source": "query",
                    "sql": "SELECT count(*) AS n FROM tasks",
                },
            }
        ]
    }


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dump(document: Any) -> bytes:
    return json.dumps(document, sort_keys=True).encode()


class TufRepository:
    """One registry: its keys, its signed metadata, and its target files."""

    def __init__(self) -> None:
        self.signers = {role: CryptoSigner.generate_ed25519() for role in _TOP_LEVEL}
        self.publisher_signers: dict[str, CryptoSigner] = {}
        self.records: dict[str, dict[str, Any]] = {}
        #: Target content by logical path, per signing role.
        self.content: dict[str, dict[str, bytes]] = {"targets": {}}
        #: The files a host serves, by path under the repository root.
        self.files: dict[str, bytes] = {}
        #: The ``package`` delegation: whether ``targets`` names it, the key
        #: it names, whether its role file is published, and the key that
        #: file is actually signed with (another one, to make it fail).
        self.package_delegated = False
        self.package_signer: CryptoSigner | None = None
        self.package_published = False
        self.package_signed_by: CryptoSigner | None = None
        self._version = 0
        self.root = Root(expires=datetime.now(UTC) + timedelta(days=365))
        for role, signer in self.signers.items():
            self.root.add_key(signer.public_key, role)
        self._sign_root()

    # --- keys and roots --------------------------------------------------------

    def _sign_root(self) -> None:
        metadata = Metadata(self.root)
        metadata.sign(self.signers["root"])
        data = metadata.to_bytes()
        self.files[f"metadata/{self.root.version}.root.json"] = data
        if self.root.version == 1:
            self.first_root = data

    def root_bytes(self) -> bytes:
        """The version 1 root, which a client is bootstrapped from."""
        return self.first_root

    def rotate_timestamp_key(self) -> None:
        """A new root version with a new timestamp key, signed by the root key."""
        old = self.signers["timestamp"]
        self.root.revoke_key(old.public_key.keyid, "timestamp")
        self.signers["timestamp"] = CryptoSigner.generate_ed25519()
        self.root.add_key(self.signers["timestamp"].public_key, "timestamp")
        self.root.version += 1
        self._sign_root()

    # --- content ------------------------------------------------------------------

    def add_publisher(
        self, prefix: str, *, name: str | None = None, verified: bool = True
    ) -> None:
        self.publisher_signers[prefix] = CryptoSigner.generate_ed25519()
        self.content.setdefault(prefix, {})
        self.records[prefix] = {
            "schema": 1,
            "prefix": prefix,
            "name": name or prefix.title(),
            "verified": verified,
        }
        self.content["targets"][f"publishers/{prefix}.json"] = _dump(
            self.records[prefix]
        )

    def add_listing(
        self,
        prefix: str,
        uid: str,
        *,
        slug: str = "thing",
        kind: str = "plugin",
        name: str = "A thing",
        versions: tuple[str, ...] = ("1.0.0",),
        definition: dict[str, Any] | None = None,
        registration: dict[str, Any] | None = None,
        images: int = 1,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Publish one listing under ``prefix``: its entry, a manifest per
        version, an avatar and ``images`` pictures. Returns the entry."""
        public_id = f"{prefix}.{slug}"
        base = f"publishers/{prefix}/{uid}/"
        files = self.content[prefix]
        if definition is None:
            definition = (
                service_plugin_definition(public_id)
                if kind == "plugin"
                else dashboard_definition()
            )

        def asset(seed: str) -> dict[str, Any]:
            data = png(f"{uid}-{seed}")
            path = f"assets/{_sha(data)}.png"
            files[base + path] = data
            return {"path": path, "sha256": _sha(data), "alt": seed}

        version_entries = []
        for version in versions:
            manifest = _dump(
                {"public_id": public_id, "kind": kind, "definition": definition}
            )
            files[f"{base}{version}/manifest.json"] = manifest
            version_entries.append(
                {
                    "version": version,
                    "manifest": f"{version}/manifest.json",
                    "sha256": _sha(manifest),
                    "release_notes": f"Release {version}.",
                }
            )
        entry: dict[str, Any] = {
            "schema": 1,
            "uid": uid,
            "public_id": public_id,
            "publisher": prefix,
            "kind": kind,
            "name": name,
            "summary": f"{name}, from the registry.",
            "avatar": asset("avatar"),
            "images": [asset(f"image-{index}") for index in range(images)],
            "versions": version_entries,
            "price": None,
        }
        if kind == "plugin":
            entry["registration"] = registration or container_registration()
        entry.update(extra or {})
        files[base + "listing.json"] = _dump(entry)
        return entry

    def add_package(self, *, publish_role: bool = True) -> None:
        """Delegate the ``package`` role; ``publish_role`` publishes its role
        file too, which the public index never does."""
        self.package_delegated = True
        self.package_signer = self.package_signer or CryptoSigner.generate_ed25519()
        self.package_published = publish_role
        self.content.setdefault("package", {})

    def set_terms(self, uid: str, terms: dict[str, Any] | bytes) -> None:
        """Sign ``entitlements/<uid>.json`` under the package role."""
        if not self.package_delegated:
            self.add_package()
        self.content["package"][f"entitlements/{uid}.json"] = (
            terms if isinstance(terms, bytes) else _dump(terms)
        )

    def remove_terms(self, uid: str) -> None:
        self.content["package"].pop(f"entitlements/{uid}.json", None)

    def remove_listing(self, prefix: str, uid: str) -> None:
        base = f"publishers/{prefix}/{uid}/"
        for path in [p for p in self.content[prefix] if p.startswith(base)]:
            del self.content[prefix][path]

    # --- signing ------------------------------------------------------------------

    def publish(
        self,
        *,
        timestamp_expires: datetime | None = None,
        publisher_expires: datetime | None = None,
    ) -> None:
        """Sign a new version of every role and serve the result."""
        self._version += 1
        version = self._version
        now = datetime.now(UTC)
        snapshot = Snapshot(version=version, expires=now + timedelta(days=7))

        roles: dict[str, DelegatedRole] = {}
        keys = {}
        for prefix, signer in self.publisher_signers.items():
            keys[signer.public_key.keyid] = signer.public_key
            roles[prefix] = DelegatedRole(
                name=prefix,
                keyids=[signer.public_key.keyid],
                threshold=1,
                terminating=True,
                paths=[
                    f"publishers/{prefix}/*/listing.json",
                    f"publishers/{prefix}/*/*/manifest.json",
                    f"publishers/{prefix}/*/assets/*",
                ],
            )
            delegated = Targets(
                version=version,
                expires=publisher_expires or now + timedelta(days=90),
            )
            for path, data in self.content[prefix].items():
                delegated.targets[path] = TargetFile.from_data(path, data, ["sha256"])
            self._serve_targets(self.content[prefix])
            metadata = Metadata(delegated)
            metadata.sign(signer)
            self.files[f"metadata/{version}.{prefix}.json"] = metadata.to_bytes()
            snapshot.meta[f"{prefix}.json"] = MetaFile(version=version)

        if self.package_delegated and self.package_signer is not None:
            signer = self.package_signer
            keys[signer.public_key.keyid] = signer.public_key
            roles["package"] = DelegatedRole(
                name="package",
                keyids=[signer.public_key.keyid],
                threshold=1,
                terminating=True,
                paths=["entitlements/*", "grants/*"],
            )
            if self.package_published:
                package = Targets(version=version, expires=now + timedelta(days=90))
                for path, data in self.content["package"].items():
                    package.targets[path] = TargetFile.from_data(path, data, ["sha256"])
                self._serve_targets(self.content["package"])
                metadata = Metadata(package)
                metadata.sign(self.package_signed_by or signer)
                self.files[f"metadata/{version}.package.json"] = metadata.to_bytes()
                snapshot.meta["package.json"] = MetaFile(version=version)

        targets = Targets(version=version, expires=now + timedelta(days=365))
        targets.delegations = Delegations(keys=keys, roles=roles)
        for path, data in self.content["targets"].items():
            targets.targets[path] = TargetFile.from_data(path, data, ["sha256"])
        self._serve_targets(self.content["targets"])
        metadata = Metadata(targets)
        metadata.sign(self.signers["targets"])
        self.files[f"metadata/{version}.targets.json"] = metadata.to_bytes()
        snapshot.meta["targets.json"] = MetaFile(version=version)

        metadata = Metadata(snapshot)
        metadata.sign(self.signers["snapshot"])
        self.files[f"metadata/{version}.snapshot.json"] = metadata.to_bytes()

        timestamp = Timestamp(
            version=version,
            expires=timestamp_expires or now + timedelta(days=1),
            snapshot_meta=MetaFile(version=version),
        )
        metadata = Metadata(timestamp)
        metadata.sign(self.signers["timestamp"])
        self.files["metadata/timestamp.json"] = metadata.to_bytes()

    def _serve_targets(self, content: dict[str, bytes]) -> None:
        for path, data in content.items():
            directory, _, name = path.rpartition("/")
            self.files[f"targets/{directory}/{_sha(data)}.{name}"] = data

    def served_path(self, path: str, prefix: str | None = None) -> str:
        """Where the current bytes of target ``path`` are served."""
        data = self.content[prefix or "targets"][path]
        directory, _, name = path.rpartition("/")
        return f"targets/{directory}/{_sha(data)}.{name}"

    def fetcher(self) -> RepositoryFetcher:
        return RepositoryFetcher(self)

    def bundle(self) -> bytes:
        """The served files as a gzipped tar, as the offline upload takes it."""
        import io
        import tarfile

        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            for path, data in sorted(self.files.items()):
                info = tarfile.TarInfo(name=f"public/{path}")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return buffer.getvalue()


def container_registration(**overrides: Any) -> dict[str, Any]:
    registration: dict[str, Any] = {
        "kind": "container",
        "image": "ghcr.io/acme/tracker@sha256:" + "0" * 64,
        "scope_ceiling": ["projects:read", "projects:write"],
    }
    registration.update(overrides)
    return registration


class RepositoryFetcher(FetcherInterface):
    """Serves a :class:`TufRepository` at :data:`BASE_URL`."""

    def __init__(self, repository: TufRepository) -> None:
        self.repository = repository
        self.requested: list[str] = []

    def _fetch(self, url: str) -> Iterator[bytes]:
        self.requested.append(url)
        if not url.startswith(BASE_URL):
            raise tuf_errors.DownloadHTTPError(f"{url} is not served here", 404)
        data = self.repository.files.get(url[len(BASE_URL) :])
        if data is None:
            raise tuf_errors.DownloadHTTPError(f"{url} not found", 404)
        return iter((data,))
