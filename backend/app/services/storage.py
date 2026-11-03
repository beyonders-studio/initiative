"""Pluggable blob storage backend.

Storage rebuild: a single seam
over blob I/O so the local filesystem (FOSS / self-host / dev) and an
S3-compatible object store (cloud, or a self-hosted Garage) become interchangeable
behind one config flag — ``STORAGE_BACKEND=local|s3``.

The backend is *dumb about tenancy*: it operates on opaque object keys (today,
the stored filename — a UUID-hex basename). Tenancy is owned by the **resolver**
(:func:`get_guild_storage`), the storage twin of ``set_rls_context``: it hands
back a backend whose keys are namespaced to the guild (``guild_<id>/`` for S3 —
the object-store expression of the schema-per-guild boundary; design §6). Callers still pass the flat
filename and own the ``/uploads/{community_id}/{filename}`` URL scheme.

Phases delivered here:
- ``LocalFilesystemStorage`` — files under ``UPLOADS_DIR/guild_<id>/`` (same
  per-guild layout as S3).
- ``S3Storage`` — boto3 against any S3-compatible endpoint; serves via streaming
  proxy (:func:`build_upload_response`) and can presign for opt-in offload.

``STORAGE_BACKEND`` defaults to ``local``; the S3 path is dormant until a bucket
is configured.
"""

from __future__ import annotations

import io
import logging
import mimetypes
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, Iterator, Protocol, runtime_checkable
from urllib.parse import quote

from fastapi.responses import FileResponse, Response, StreamingResponse

from app.core.config import settings
from app.services.storage_config import current_storage_config

if TYPE_CHECKING:  # botocore imported lazily at call time; type-only here
    from botocore.client import BaseClient

    from app.services.storage_config import ResolvedStorageConfig

logger = logging.getLogger(__name__)


# Streaming proxy chunk size for S3 GetObject bodies.
_STREAM_CHUNK = 64 * 1024
#: How much :func:`open_seekable` fetches at a time.
_RANGE_READ = 256 * 1024
#: What a file arriving in parts is stored under (``app.services.resumable``),
#: and keeps once an endpoint takes it.
STAGING_PREFIX = "resumable-"

# S3 error codes that mean "object/bucket not here" rather than a real failure.
_S3_MISSING_CODES = {"404", "NoSuchKey", "NoSuchBucket", "NotFound"}


def is_flat_storage_key(key: str) -> bool:
    """True if ``key`` has no path components — it already equals its own
    basename. Both backends key objects by ``Path(key).name``, so a value used
    as both a stored identity and a storage key must be flat for the two to
    refer to the same object."""
    return bool(key) and Path(key).name == key


#: Stored types a served upload is rendered inline as. Raster pictures only:
#: an ``<img>`` draws these and nothing about them is markup. Anything else —
#: an SVG, an uploaded file, a type nothing recognizes — is handed over as a
#: download in its own sandbox (:data:`USER_CONTENT_CSP`).
INLINE_UPLOAD_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/tiff",
        "image/x-icon",
        "image/vnd.microsoft.icon",
    }
)

#: How a stored file is served wherever a browser could render it as a page:
#: in a sandbox of its own, loading nothing but its own inline styles.
USER_CONTENT_CSP = "sandbox; default-src 'none'; style-src 'unsafe-inline'"


def content_disposition_attachment(filename: str) -> str:
    """Build a safe ``attachment`` Content-Disposition value.

    Mirrors Starlette's ``FileResponse`` so a user-supplied filename containing a
    double-quote or non-ASCII char can't break out of the header: RFC 5987
    ``filename*=utf-8''…`` when the name needs escaping, plain ``filename="…"``
    otherwise.
    """
    quoted = quote(filename)
    if quoted != filename:
        return f"attachment; filename*=utf-8''{quoted}"
    return f'attachment; filename="{filename}"'


@dataclass
class ReadableBlob:
    """A served blob, backend-agnostic.

    Local sets ``path`` (so the serve adapter keeps ``FileResponse`` sendfile +
    range support); S3 sets ``stream``. Both populate ``content_type`` and
    ``content_length`` — S3 from the object metadata, local from the file's
    extension/size — so the blob is consistent regardless of backend.
    """

    path: Path | None = None
    stream: Iterator[bytes] | None = None
    content_type: str | None = None
    content_length: int | None = None
    #: For a stream of part of the object, the ``Content-Range`` it answers.
    content_range: str | None = None


def requested_range(header: str | None) -> str | None:
    """A request's ``Range`` header when it asks for one range of bytes
    (``bytes=0-499``, ``bytes=500-``, ``bytes=-500``); ``None`` for anything
    else, which is served whole."""
    if not header or not header.startswith("bytes="):
        return None
    first, dash, last = header.removeprefix("bytes=").partition("-")
    digits = first + last
    if not dash or not digits or not (digits.isascii() and digits.isdigit()):
        return None
    # No stored file runs to a petabyte; a longer bound is served whole.
    if max(len(first), len(last)) > 15:
        return None
    if first and last and int(first) > int(last):
        return None
    return header


@runtime_checkable
class StorageBackend(Protocol):
    """Object-store contract. ``key`` is an opaque object name (a flat filename);
    the resolver applies any tenant prefix before the backend sees it."""

    def write(
        self, key: str, data: bytes, *, content_type: str | None = None
    ) -> None: ...

    def write_file(
        self, key: str, path: "Path", *, content_type: str | None = None
    ) -> None:
        """Store what is already on disk, without reading it into memory first.

        The caller owns ``path`` and deletes it afterwards. This exists for
        artifacts assembled on disk because they are too big to hold — a whole
        community's export — so an implementation that just reads the file and
        calls ``write`` would defeat the point.
        """
        ...

    def delete(self, key: str) -> bool: ...

    def copy(self, src_key: str, dst_key: str) -> bool: ...

    def delete_prefix(self) -> int: ...

    def exists(self, key: str) -> bool: ...

    def open_readable(
        self, key: str, *, byte_range: str | None = None
    ) -> ReadableBlob | None: ...

    # --- A file staged in parts (``app.services.resumable``) -----------------
    # ``state`` is the backend's own record of the parts, kept by the caller
    # between requests; each call returns it updated. ``stored`` in it counts
    # the bytes kept as parts, ``tail`` those kept apart until the next, and
    # ``store`` the kind of store that holds them.

    def start_parts(
        self, key: str, *, part_bytes: int, length: int | None = None
    ) -> dict:
        """Begin a file of ``length`` bytes arriving in parts. Only
        :class:`EncryptedStorage` reads ``length``: its header carries it."""
        ...

    def holds_parts(self, state: dict) -> bool:
        """Whether this backend holds the parts ``state`` records: not when
        the community's storage moved since they were started."""
        ...

    def add_part(self, key: str, state: dict, data: bytes) -> dict:
        """Keep ``data`` as the next part."""
        ...

    def keep_tail(self, key: str, state: dict, data: bytes) -> dict:
        """Keep ``data``, the last bytes a request brought, for the next one."""
        ...

    def take_tail(self, key: str, state: dict) -> tuple[bytes, dict]:
        """The bytes :meth:`keep_tail` kept, to lead the next part."""
        ...

    def finish_parts(self, key: str, state: dict) -> None:
        """Make the parts the object ``key``."""
        ...

    def drop_parts(self, key: str, state: dict) -> None:
        """Throw away the parts, the tail and the object."""
        ...

    def presign_get(
        self, key: str, *, ttl: int, filename: str | None = None
    ) -> str | None: ...


class LocalFilesystemStorage:
    """Stores objects as files under ``UPLOADS_DIR[/<prefix>]``.

    ``key`` is the stored filename; ``prefix`` is the resolver-supplied guild
    namespace (``guild_<id>/``), so a guild's blobs live under
    ``UPLOADS_DIR/guild_<id>/`` — the same per-guild layout as the S3 backend.
    Keys are reduced to a basename before they touch the filesystem, so a key
    can never escape the (prefixed) base directory; this centralizes the
    path-traversal guard the two serve endpoints previously duplicated. The
    directory is created on demand.
    """

    def __init__(self, base_dir: str | None = None, prefix: str = "") -> None:
        self._base_dir = base_dir
        self._prefix = prefix

    def _root(self) -> Path:
        return Path(self._base_dir or settings.UPLOADS_DIR)

    def _dir(self) -> Path:
        # ``Path / ""`` is a no-op, so an empty prefix yields the flat root.
        path = self._root() / self._prefix
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _safe_path(self, key: str) -> Path | None:
        name = Path(key).name
        if not name:
            return None
        base = self._dir()
        try:
            target = (base / name).resolve()
            target.relative_to(base.resolve())
        except ValueError:
            return None
        return target

    def write(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        # content_type is meaningless on a filesystem (inferred at serve time);
        # accepted for protocol parity with S3 and ignored.
        target = self._safe_path(key)
        if target is None:
            raise ValueError(f"Invalid storage key: {key!r}")
        target.write_bytes(data)

    def write_file(
        self, key: str, path: Path, *, content_type: str | None = None
    ) -> None:
        import shutil

        target = self._safe_path(key)
        if target is None:
            raise ValueError(f"Invalid storage key: {key!r}")
        # copyfile, not move: the source may be on a different filesystem
        # (a temp dir), and it streams rather than loading the file. Into a
        # file beside the target first, then renamed over it, so replacing an
        # object in place (the encryption backfill) never leaves half of one.
        staging = target.with_name(f".{target.name}.writing")
        try:
            shutil.copyfile(path, staging)
            os.replace(staging, target)
        finally:
            staging.unlink(missing_ok=True)

    def delete(self, key: str) -> bool:
        target = self._safe_path(key)
        if target is None:
            return False
        try:
            if target.exists() and target.is_file():
                target.unlink()
                return True
        except OSError as exc:
            logger.warning("Failed to delete blob %s: %s", target, exc)
        return False

    def copy(self, src_key: str, dst_key: str) -> bool:
        src = self._safe_path(src_key)
        dst = self._safe_path(dst_key)
        if src is None or dst is None or not src.exists():
            return False
        try:
            shutil.copy2(src, dst)
            return True
        except OSError as exc:
            logger.error("Failed to copy blob %s -> %s: %s", src, dst, exc)
            return False

    def delete_prefix(self) -> int:
        """Remove this backend's whole namespace dir (``UPLOADS_DIR/<prefix>``).

        Used to tear down a guild's content on deprovision. Refuses an empty
        prefix so it can never wipe the entire uploads root. Returns the number
        of files removed.
        """
        if not self._prefix:
            raise ValueError(
                "delete_prefix refused: empty prefix would target all uploads"
            )
        target_dir = self._root() / self._prefix
        if not target_dir.is_dir():
            return 0
        total = sum(1 for p in target_dir.rglob("*") if p.is_file())
        shutil.rmtree(target_dir, ignore_errors=True)
        # Count only what actually went away and surface the rest: a file rmtree
        # couldn't remove (e.g. permissions) would otherwise be silently reported
        # as deleted — the very orphan it's meant to prevent.
        remaining = (
            [p for p in target_dir.rglob("*") if p.is_file()]
            if target_dir.exists()
            else []
        )
        for leftover in remaining:
            logger.error("delete_prefix could not remove %s", leftover)
        return total - len(remaining)

    def exists(self, key: str) -> bool:
        target = self._safe_path(key)
        return bool(target and target.is_file())

    def iter_keys(self) -> Iterator[str]:
        """Every object in this namespace."""
        directory = self._root() / self._prefix
        if directory.is_dir():
            for entry in sorted(directory.iterdir()):
                if entry.is_file() and not entry.name.startswith("."):
                    yield entry.name

    def resolve_readable(self, key: str) -> Path | None:
        """Filesystem path for a key, or None. Retained for local-only callers."""
        target = self._safe_path(key)
        if target is None or not target.is_file():
            return None
        return target

    def open_readable(
        self, key: str, *, byte_range: str | None = None
    ) -> ReadableBlob | None:
        # ``byte_range`` is answered by the ``FileResponse`` the path becomes.
        target = self.resolve_readable(key)
        if target is None:
            return None
        # The filesystem stores no object metadata (unlike S3), so derive the
        # content-type from the extension — keeping ReadableBlob consistent across
        # backends, and giving a cross-store copy a type to carry over.
        return ReadableBlob(
            path=target,
            content_type=mimetypes.guess_type(target.name)[0],
            content_length=target.stat().st_size,
        )

    def start_parts(
        self, key: str, *, part_bytes: int, length: int | None = None
    ) -> dict:
        target = self._safe_path(key)
        if target is None:
            raise ValueError(f"Invalid storage key: {key!r}")
        target.write_bytes(b"")
        return {"store": "local", "stored": 0, "tail": 0, "part_bytes": part_bytes}

    def holds_parts(self, state: dict) -> bool:
        return state.get("store") == "local"

    def add_part(self, key: str, state: dict, data: bytes) -> dict:
        target = self._safe_path(key)
        if target is None:
            raise ValueError(f"Invalid storage key: {key!r}")
        with target.open("r+b") as handle:
            # Bytes past what was recorded are from a request that failed.
            handle.truncate(state["stored"])
            handle.seek(state["stored"])
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        return {**state, "stored": state["stored"] + len(data)}

    def keep_tail(self, key: str, state: dict, data: bytes) -> dict:
        # A file on disk takes a part of any size.
        return self.add_part(key, state, data) if data else state

    def take_tail(self, key: str, state: dict) -> tuple[bytes, dict]:
        return b"", state

    def finish_parts(self, key: str, state: dict) -> None:
        return None

    def drop_parts(self, key: str, state: dict) -> None:
        self.delete(key)

    def presign_get(
        self, key: str, *, ttl: int, filename: str | None = None
    ) -> str | None:
        # A filesystem has no signed URLs; local content is always proxy-served.
        return None


class S3Storage:
    """S3-compatible object store (Garage, MinIO, R2, …) via boto3.

    Dumb about tenancy: it reads/writes keys within the ``(bucket, client,
    prefix)`` the resolver handed it. ``prefix`` is the guild namespace
    (``guild_<id>/``); the resolver owns it. Keys are reduced to a basename
    before the prefix is applied, mirroring the local traversal guard.
    """

    def __init__(
        self,
        *,
        bucket: str,
        client: "BaseClient",
        prefix: str = "",
    ) -> None:
        self._bucket = bucket
        self._client = client
        self._prefix = prefix

    def _object_key(self, key: str) -> str:
        name = Path(key).name
        if not name:
            raise ValueError(f"Invalid storage key: {key!r}")
        return f"{self._prefix}{name}"

    def _head(self, object_key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self._bucket, Key=object_key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _S3_MISSING_CODES:
                return False
            raise

    def write(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(
            Bucket=self._bucket, Key=self._object_key(key), Body=data, **extra
        )

    def write_file(
        self, key: str, path: Path, *, content_type: str | None = None
    ) -> None:
        # upload_file chunks large objects into a multipart upload itself, so
        # the body never has to fit in memory.
        self._client.upload_file(
            str(path),
            self._bucket,
            self._object_key(key),
            ExtraArgs={"ContentType": content_type} if content_type else None,
        )

    def delete(self, key: str) -> bool:
        object_key = self._object_key(key)
        # head first so the bool return matches local semantics (missing -> False);
        # delete_object itself is idempotent.
        if not self._head(object_key):
            return False
        self._client.delete_object(Bucket=self._bucket, Key=object_key)
        return True

    def copy(self, src_key: str, dst_key: str) -> bool:
        src = self._object_key(src_key)
        dst = self._object_key(dst_key)
        if not self._head(src):
            return False
        # Server-side copy — no bytes through the app (design §7 / tier migration).
        self._client.copy_object(
            Bucket=self._bucket,
            Key=dst,
            CopySource={"Bucket": self._bucket, "Key": src},
        )
        return True

    def delete_prefix(self) -> int:
        """Delete every object under this backend's namespace (``self._prefix``).

        Used to tear down a guild's content on deprovision, files still
        arriving in parts included. Refuses an empty prefix so it can never
        target the whole bucket. Returns the number of objects deleted.
        """
        if not self._prefix:
            raise ValueError(
                "delete_prefix refused: empty prefix would target the whole bucket"
            )
        deleted = 0
        token: str | None = None
        while True:
            kwargs: dict = {"Bucket": self._bucket, "Prefix": self._prefix}
            if token:
                kwargs["ContinuationToken"] = token
            resp = self._client.list_objects_v2(**kwargs)
            objects = [{"Key": o["Key"]} for o in resp.get("Contents", [])]
            if objects:
                result = self._client.delete_objects(
                    Bucket=self._bucket, Delete={"Objects": objects, "Quiet": True}
                )
                # Quiet=True returns only per-object failures; surface them and
                # count only the ones that actually deleted (an unlogged failure
                # would silently re-orphan the very blobs this is meant to purge).
                errors = result.get("Errors") or []
                for err in errors:
                    logger.error(
                        "delete_prefix could not delete %s: %s %s",
                        err.get("Key"),
                        err.get("Code"),
                        err.get("Message"),
                    )
                deleted += len(objects) - len(errors)
            if resp.get("IsTruncated"):
                token = resp.get("NextContinuationToken")
            else:
                break
        # A file still arriving in parts is no object yet, so the listing
        # above does not see it.
        markers: dict = {}
        while True:
            resp = self._client.list_multipart_uploads(
                Bucket=self._bucket, Prefix=self._prefix, **markers
            )
            for upload in resp.get("Uploads", []):
                self._client.abort_multipart_upload(
                    Bucket=self._bucket, Key=upload["Key"], UploadId=upload["UploadId"]
                )
            if not resp.get("IsTruncated"):
                break
            markers = {
                "KeyMarker": resp["NextKeyMarker"],
                "UploadIdMarker": resp["NextUploadIdMarker"],
            }
        return deleted

    def exists(self, key: str) -> bool:
        return self._head(self._object_key(key))

    def iter_keys(self) -> Iterator[str]:
        """Every object in this namespace."""
        token: str | None = None
        while True:
            kwargs: dict = {"Bucket": self._bucket, "Prefix": self._prefix}
            if token:
                kwargs["ContinuationToken"] = token
            resp = self._client.list_objects_v2(**kwargs)
            for item in resp.get("Contents", []):
                yield item["Key"][len(self._prefix) :]
            if not resp.get("IsTruncated"):
                return
            token = resp.get("NextContinuationToken")

    def open_readable(
        self, key: str, *, byte_range: str | None = None
    ) -> ReadableBlob | None:
        from botocore.exceptions import ClientError

        params = {"Bucket": self._bucket, "Key": self._object_key(key)}
        try:
            try:
                obj = self._client.get_object(
                    **params, **({"Range": byte_range} if byte_range else {})
                )
            except ClientError as exc:
                # A range past the end is answered with the whole object, as
                # a server may answer any range.
                if exc.response.get("Error", {}).get("Code") != "InvalidRange":
                    raise
                obj = self._client.get_object(**params)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _S3_MISSING_CODES:
                return None
            raise
        return ReadableBlob(
            stream=obj["Body"].iter_chunks(chunk_size=_STREAM_CHUNK),
            content_type=obj.get("ContentType"),
            content_length=obj.get("ContentLength"),
            content_range=obj.get("ContentRange"),
        )

    def _tail_key(self, key: str) -> str:
        return self._object_key(f"{Path(key).name}-tail")

    def start_parts(
        self, key: str, *, part_bytes: int, length: int | None = None
    ) -> dict:
        upload = self._client.create_multipart_upload(
            Bucket=self._bucket, Key=self._object_key(key)
        )
        return {
            "store": "s3",
            "upload_id": upload["UploadId"],
            "parts": [],
            "stored": 0,
            "tail": 0,
            "part_bytes": part_bytes,
        }

    def holds_parts(self, state: dict) -> bool:
        return state.get("store") == "s3"

    def add_part(self, key: str, state: dict, data: bytes) -> dict:
        number = len(state["parts"]) + 1
        answer = self._client.upload_part(
            Bucket=self._bucket,
            Key=self._object_key(key),
            UploadId=state["upload_id"],
            PartNumber=number,
            Body=data,
        )
        return {
            **state,
            "parts": [*state["parts"], {"n": number, "etag": answer["ETag"]}],
            "stored": state["stored"] + len(data),
            "tail": 0,
        }

    def keep_tail(self, key: str, state: dict, data: bytes) -> dict:
        # Every part but the last is a whole ``part_bytes``, so the parts stay
        # within S3's limit; what a request leaves short of one waits as an
        # object of its own. It starts with the tail it replaces, so reading
        # only what the caller recorded gets that tail back should the record
        # of this one not land.
        if not data:
            return state
        self._client.put_object(Bucket=self._bucket, Key=self._tail_key(key), Body=data)
        return {**state, "tail": len(data)}

    def take_tail(self, key: str, state: dict) -> tuple[bytes, dict]:
        if not state["tail"]:
            return b"", state
        tail = self._client.get_object(Bucket=self._bucket, Key=self._tail_key(key))
        return tail["Body"].read()[: state["tail"]], {**state, "tail": 0}

    def finish_parts(self, key: str, state: dict) -> None:
        from botocore.exceptions import ClientError

        if state["parts"]:
            try:
                self._client.complete_multipart_upload(
                    Bucket=self._bucket,
                    Key=self._object_key(key),
                    UploadId=state["upload_id"],
                    MultipartUpload={
                        "Parts": [
                            {"PartNumber": part["n"], "ETag": part["etag"]}
                            for part in state["parts"]
                        ]
                    },
                )
            except ClientError as exc:
                # Finished once already, by a request whose record did not
                # land: the object is there.
                code = exc.response.get("Error", {}).get("Code")
                if code != "NoSuchUpload" or not self._head(self._object_key(key)):
                    raise
        else:
            # An empty file has no part to complete.
            self._abort(key, state)
            self._client.put_object(
                Bucket=self._bucket, Key=self._object_key(key), Body=b""
            )
        try:
            self._client.delete_object(Bucket=self._bucket, Key=self._tail_key(key))
        except ClientError:
            # A tail left over costs storage and nothing else; dropping the
            # parts takes it.
            logger.warning("tail_delete_failed key=%s", key, exc_info=True)

    def _abort(self, key: str, state: dict) -> None:
        from botocore.exceptions import ClientError

        try:
            self._client.abort_multipart_upload(
                Bucket=self._bucket,
                Key=self._object_key(key),
                UploadId=state["upload_id"],
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "NoSuchUpload":
                raise

    def drop_parts(self, key: str, state: dict) -> None:
        self._abort(key, state)
        self._client.delete_object(Bucket=self._bucket, Key=self._tail_key(key))
        self.delete(key)

    def presign_get(
        self, key: str, *, ttl: int, filename: str | None = None
    ) -> str | None:
        params: dict[str, str] = {"Bucket": self._bucket, "Key": self._object_key(key)}
        if filename:
            params["ResponseContentDisposition"] = content_disposition_attachment(
                filename
            )
        return self._client.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=ttl
        )


class DualReadStorage:
    """Local→S3 cutover safety net (enabled by ``S3_LOCAL_FALLBACK``).

    Writes and deletes go to the primary (S3); reads fall back to the local
    fallback on a miss, so blobs the backfill hasn't copied yet still serve while
    a deployment is being moved onto S3. ``delete_prefix`` purges **both** stores
    (guild teardown). Flip the flag off once the backfill is verified complete.
    """

    def __init__(self, *, primary: StorageBackend, fallback: StorageBackend) -> None:
        self._primary = primary
        self._fallback = fallback

    def write(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        self._primary.write(key, data, content_type=content_type)

    def write_file(
        self, key: str, path: Path, *, content_type: str | None = None
    ) -> None:
        self._primary.write_file(key, path, content_type=content_type)

    def delete(self, key: str) -> bool:
        # Remove from both stores so a deleted blob can't reappear via fallback.
        primary_deleted = self._primary.delete(key)
        fallback_deleted = self._fallback.delete(key)
        return primary_deleted or fallback_deleted

    def copy(self, src_key: str, dst_key: str) -> bool:
        if self._primary.copy(src_key, dst_key):
            return True
        # Source not yet backfilled into S3: read it from local, write to S3.
        blob = self._fallback.open_readable(src_key)
        if blob is None or blob.path is None:
            return False
        # Carry the source's content-type onto the S3 object so it isn't served as
        # octet-stream once the fallback window closes (open_readable populates it
        # for both backends).
        self._primary.write(
            dst_key, blob.path.read_bytes(), content_type=blob.content_type
        )
        return True

    def delete_prefix(self) -> int:
        return self._primary.delete_prefix() + self._fallback.delete_prefix()

    def exists(self, key: str) -> bool:
        return self._primary.exists(key) or self._fallback.exists(key)

    def iter_keys(self) -> Iterator[str]:
        """Every object in either store, once."""
        seen: set[str] = set()
        for store in (self._primary, self._fallback):
            for key in store.iter_keys():  # type: ignore[attr-defined]
                if key not in seen:
                    seen.add(key)
                    yield key

    def open_readable(
        self, key: str, *, byte_range: str | None = None
    ) -> ReadableBlob | None:
        # The whole point of the fallback window is "keep serving during the
        # cutover." A clean miss (None) falls through to local; so does an S3
        # *error* (auth/signature/transient) — we log it loudly so a real
        # misconfiguration is still visible, but a half-migrated deployment keeps
        # serving from local instead of 500ing. Once the backfill is verified and
        # S3 reads are healthy, turn S3_LOCAL_FALLBACK off.
        try:
            blob = self._primary.open_readable(key, byte_range=byte_range)
        except Exception:
            logger.warning(
                "S3 read failed for %r; serving from local fallback "
                "(S3_LOCAL_FALLBACK on). Resolve the S3 error before disabling "
                "fallback.",
                key,
                exc_info=True,
            )
            blob = None
        return blob or self._fallback.open_readable(key, byte_range=byte_range)

    def start_parts(
        self, key: str, *, part_bytes: int, length: int | None = None
    ) -> dict:
        return self._primary.start_parts(key, part_bytes=part_bytes)

    def _staging(self, state: dict) -> StorageBackend:
        """The store an upload's parts were started in, so one begun before
        the move carries on where it began."""
        return self._fallback if self._fallback.holds_parts(state) else self._primary

    def holds_parts(self, state: dict) -> bool:
        return self._staging(state).holds_parts(state)

    def add_part(self, key: str, state: dict, data: bytes) -> dict:
        return self._staging(state).add_part(key, state, data)

    def keep_tail(self, key: str, state: dict, data: bytes) -> dict:
        return self._staging(state).keep_tail(key, state, data)

    def take_tail(self, key: str, state: dict) -> tuple[bytes, dict]:
        return self._staging(state).take_tail(key, state)

    def finish_parts(self, key: str, state: dict) -> None:
        self._staging(state).finish_parts(key, state)

    def drop_parts(self, key: str, state: dict) -> None:
        self._staging(state).drop_parts(key, state)

    def presign_get(
        self, key: str, *, ttl: int, filename: str | None = None
    ) -> str | None:
        # Only S3 can sign; if the object is still local-only, return None so the
        # caller proxy-serves it instead.
        if self._primary.exists(key):
            return self._primary.presign_get(key, ttl=ttl, filename=filename)
        return None


#: Plaintext a stream is read in while an object is encrypted from disk.
_SEAL_READ = 1024 * 1024
_TAIL_NONCE_LEN = 12


class EncryptedStorage:
    """A community's store, with every object encrypted by the app.

    Wraps whatever backend holds the community (local, S3, or the cutover's
    dual read) when ``STORAGE_ENCRYPTION`` is set: :func:`get_guild_storage`
    returns one of these, so no caller knows. Each object is written in the
    format of :mod:`app.core.storage_crypto`, under a key of its own wrapped by
    the community's storage key (:mod:`app.services.storage_keys`), and read
    back the same way — a byte range reads only the chunks it covers.

    Reads tell the formats apart by the header, so an object stored before
    encryption was on reads as it is until the backfill encrypts it. Evidence
    is encrypted already, under its own scheme (``app.core.blob_crypto``), and
    passes through untouched; so do deletes, copies within the community and
    the namespace purge, none of which reads a byte.

    Nothing is ever signed for direct download: the store holds ciphertext.
    """

    def __init__(self, inner: StorageBackend, *, guild_id: int, keyring: Any) -> None:
        self._inner = inner
        self._guild_id = int(guild_id)
        self._keyring = keyring

    @property
    def inner(self) -> StorageBackend:
        return self._inner

    @staticmethod
    def _untouched(key: str) -> bool:
        return Path(key).name.startswith(EVIDENCE_KEY_PREFIX)

    def _writes_encrypted(self, key: str) -> bool:
        return self._keyring.encrypts and not self._untouched(key)

    def _key(self, *, create: bool) -> tuple[bytes, int]:
        from app.core.storage_crypto import StorageCryptoError

        found = self._keyring.key_for(self._guild_id, create=create)
        if found is None:
            raise StorageCryptoError(
                f"community {self._guild_id} holds no storage key: its encrypted "
                "objects were destroyed with it"
            )
        return found

    def _dek(self, header: Any) -> bytes:
        from app.core import storage_crypto

        key, generation = self._key(create=False)
        if header.generation != generation:
            raise storage_crypto.StorageCryptoError(
                f"the object is under key generation {header.generation}, the "
                f"community holds {generation}"
            )
        return storage_crypto.unwrap(header, key, guild_id=self._guild_id)

    # --- Untouched ----------------------------------------------------------

    def delete(self, key: str) -> bool:
        return self._inner.delete(key)

    def copy(self, src_key: str, dst_key: str) -> bool:
        # The header binds the community, not the key, so a copy within it
        # stays server-side.
        return self._inner.copy(src_key, dst_key)

    def delete_prefix(self) -> int:
        return self._inner.delete_prefix()

    def exists(self, key: str) -> bool:
        return self._inner.exists(key)

    def presign_get(
        self, key: str, *, ttl: int, filename: str | None = None
    ) -> str | None:
        # The store may hold ciphertext for any key: the caller proxy-serves.
        return None

    # --- Writes -------------------------------------------------------------

    def _in_the_clear(self, key: str) -> None:
        # Encryption unset with keys left: what is stored now is in the clear,
        # so the community is not caught up any more.
        if not self._untouched(key):
            self._keyring.stored_in_the_clear(self._guild_id)

    def write(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        if not self._writes_encrypted(key):
            self._in_the_clear(key)
            self._inner.write(key, data, content_type=content_type)
            return
        from app.core import storage_crypto

        community_key, generation = self._key(create=True)
        self._inner.write(
            key,
            storage_crypto.encrypt(
                data, community_key, guild_id=self._guild_id, generation=generation
            ),
            content_type=content_type,
        )

    def write_file(
        self, key: str, path: Path, *, content_type: str | None = None
    ) -> None:
        if not self._writes_encrypted(key):
            self._in_the_clear(key)
            self._inner.write_file(key, path, content_type=content_type)
            return
        import tempfile

        from app.core import storage_crypto

        community_key, generation = self._key(create=True)
        header, dek = storage_crypto.new_header(
            community_key,
            guild_id=self._guild_id,
            length=path.stat().st_size,
            generation=generation,
        )
        sealer = storage_crypto.Sealer(header, dek, guild_id=self._guild_id)
        with tempfile.NamedTemporaryFile(delete=False) as out:
            sealed_path = Path(out.name)
            try:
                out.write(header.pack())
                with path.open("rb") as source:
                    while piece := source.read(_SEAL_READ):
                        out.write(sealer.feed(piece))
                out.write(sealer.feed(b""))
            except BaseException:
                sealed_path.unlink(missing_ok=True)
                raise
        try:
            self._inner.write_file(key, sealed_path, content_type=content_type)
        finally:
            sealed_path.unlink(missing_ok=True)

    # --- Reads --------------------------------------------------------------

    @staticmethod
    def _leading(blob: ReadableBlob, size: int) -> bytes:
        if blob.path is not None:
            with blob.path.open("rb") as handle:
                return handle.read(size)
        data = bytearray()
        for piece in blob.stream or ():
            data += piece
            if len(data) >= size:
                break
        return bytes(data[:size])

    def _stored_range(
        self, key: str, probe: ReadableBlob, start: int, end: int
    ) -> Iterator[bytes]:
        """Stored bytes ``start``..``end`` inclusive."""
        if probe.path is not None:
            with probe.path.open("rb") as handle:
                handle.seek(start)
                left = end - start + 1
                while left > 0:
                    piece = handle.read(min(_STREAM_CHUNK, left))
                    if not piece:
                        return
                    left -= len(piece)
                    yield piece
            return
        blob = self._inner.open_readable(key, byte_range=f"bytes={start}-{end}")
        if blob is not None:
            yield from blob.stream or ()

    def _probe(self, key: str) -> tuple[ReadableBlob, Any] | None:
        """The object's first bytes, and its header where it has one."""
        from app.core import storage_crypto

        probe = self._inner.open_readable(
            key, byte_range=f"bytes=0-{storage_crypto.HEADER_SIZE - 1}"
        )
        if probe is None:
            return None
        lead = self._leading(probe, storage_crypto.HEADER_SIZE)
        return probe, storage_crypto.parse_header(lead)

    def open_readable(
        self, key: str, *, byte_range: str | None = None
    ) -> ReadableBlob | None:
        if self._untouched(key):
            return self._inner.open_readable(key, byte_range=byte_range)
        from app.core import storage_crypto

        probed = self._probe(key)
        if probed is None:
            return None
        probe, header = probed
        if header is None:
            # Stored before encryption was on: as it is.
            return self._inner.open_readable(key, byte_range=byte_range)
        dek = self._dek(header)
        wanted = storage_crypto.plaintext_range(header, byte_range)
        start, end = wanted if wanted else (0, header.length - 1)
        size = header.chunk_size
        first, last = (start // size, end // size) if header.length else (0, 0)
        stored_start = header.chunk_span(first)[0]
        stored_end = header.chunk_span(last)[1] - 1
        return ReadableBlob(
            stream=storage_crypto.decrypt_range(
                self._stored_range(key, probe, stored_start, stored_end),
                header,
                dek,
                guild_id=self._guild_id,
                first=first,
                last=last,
                start=start,
                end=end,
            ),
            content_type=probe.content_type,
            content_length=end - start + 1 if header.length else 0,
            content_range=(
                f"bytes {start}-{end}/{header.length}" if wanted is not None else None
            ),
        )

    def is_encrypted(self, key: str) -> bool | None:
        """Whether ``key`` is stored encrypted; ``None`` where it is missing."""
        probed = self._probe(key)
        return None if probed is None else probed[1] is not None

    def encrypt_in_place(self, key: str) -> bool:
        """Re-write ``key``, stored before encryption was on, encrypted.
        Returns whether it did: not for an object already encrypted, missing,
        or one encryption leaves alone (evidence)."""
        if not self._writes_encrypted(key):
            return False
        import tempfile

        probed = self._probe(key)
        if probed is None or probed[1] is not None:
            return False
        blob = self._inner.open_readable(key)
        if blob is None:
            return False
        if blob.path is not None:
            self.write_file(key, blob.path, content_type=blob.content_type)
            return True
        with tempfile.NamedTemporaryFile() as plain:
            for piece in blob.stream or ():
                plain.write(piece)
            plain.flush()
            self.write_file(key, Path(plain.name), content_type=blob.content_type)
        return True

    # --- A file staged in parts ---------------------------------------------
    # The plaintext state the caller keeps (``stored``, ``tail``,
    # ``part_bytes``) sits beside the inner backend's own state (``inner``,
    # counting stored bytes) and the object's header (``enc``), which carries
    # its wrapped key from one request to the next. An upload begun before
    # encryption was on has no ``enc``, and finishes as it began.

    @staticmethod
    def _tail_key(key: str) -> str:
        return f"{Path(key).name}-etail"

    def _tail_aad(self, key: str) -> bytes:
        import struct

        return b"tail" + struct.pack(">Q", self._guild_id) + Path(key).name.encode()

    def _staged_header(self, state: dict) -> Any:
        import base64

        from app.core import storage_crypto

        header = storage_crypto.parse_header(base64.b64decode(state["enc"]["header"]))
        if header is None:
            raise storage_crypto.StorageCryptoError("the upload's header is unreadable")
        return header

    def start_parts(
        self, key: str, *, part_bytes: int, length: int | None = None
    ) -> dict:
        if not self._writes_encrypted(key):
            self._in_the_clear(key)
            return self._inner.start_parts(key, part_bytes=part_bytes)
        if length is None:
            # The header carries the length; without it the file would have to
            # be stored in the clear, which an encrypting store never does.
            raise ValueError(
                "an encrypted store starts a file in parts with its length"
            )
        import base64

        from app.core import storage_crypto

        community_key, generation = self._key(create=True)
        header, dek = storage_crypto.new_header(
            community_key, guild_id=self._guild_id, length=length, generation=generation
        )
        # Every part but the last ends on a chunk boundary, so none straddles two.
        chunk = header.chunk_size
        part = -(-part_bytes // chunk) * chunk
        inner_state = self._inner.start_parts(key, part_bytes=part)
        state = {
            "store": inner_state.get("store"),
            "stored": 0,
            "tail": 0,
            "part_bytes": part,
            "inner": inner_state,
            "enc": {"header": base64.b64encode(header.pack()).decode(), "index": 0},
        }
        if length == 0:
            # Finished the moment it is created: its one empty chunk now.
            sealer = storage_crypto.Sealer(header, dek, guild_id=self._guild_id)
            state["inner"] = self._inner.add_part(
                key, inner_state, header.pack() + sealer.feed(b"")
            )
            state["enc"]["index"] = sealer.index
        return state

    def holds_parts(self, state: dict) -> bool:
        return self._inner.holds_parts(state["inner"] if "enc" in state else state)

    def add_part(self, key: str, state: dict, data: bytes) -> dict:
        if "enc" not in state:
            return self._inner.add_part(key, state, data)
        from app.core import storage_crypto

        header = self._staged_header(state)
        index = state["enc"]["index"]
        sealer = storage_crypto.Sealer(
            header, self._dek(header), guild_id=self._guild_id, index=index
        )
        sealed = sealer.feed(data)
        if sealer.pending:
            raise storage_crypto.StorageCryptoError(
                "a part ends inside a chunk and is not the last"
            )
        if index == 0:
            sealed = header.pack() + sealed
        return {
            **state,
            "inner": self._inner.add_part(key, state["inner"], sealed),
            "stored": state["stored"] + len(data),
            "tail": 0,
            "enc": {**state["enc"], "index": sealer.index},
        }

    def keep_tail(self, key: str, state: dict, data: bytes) -> dict:
        if "enc" not in state:
            return self._inner.keep_tail(key, state, data)
        if not data:
            return state
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        dek = self._dek(self._staged_header(state))
        nonce = os.urandom(_TAIL_NONCE_LEN)
        self._inner.write(
            self._tail_key(key),
            nonce + AESGCM(dek).encrypt(nonce, data, self._tail_aad(key)),
        )
        return {**state, "tail": len(data)}

    def take_tail(self, key: str, state: dict) -> tuple[bytes, dict]:
        if "enc" not in state:
            return self._inner.take_tail(key, state)
        if not state["tail"]:
            return b"", state
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        from app.core.storage_crypto import StorageCryptoError

        dek = self._dek(self._staged_header(state))
        blob = self._inner.open_readable(self._tail_key(key))
        if blob is None:
            raise StorageCryptoError("the upload's kept tail is missing")
        raw = (
            blob.path.read_bytes()
            if blob.path is not None
            else b"".join(blob.stream or ())
        )
        try:
            data = AESGCM(dek).decrypt(
                raw[:_TAIL_NONCE_LEN], raw[_TAIL_NONCE_LEN:], self._tail_aad(key)
            )
        except InvalidTag as exc:
            raise StorageCryptoError("the upload's kept tail does not decrypt") from exc
        return data[: state["tail"]], {**state, "tail": 0}

    def _drop_tail(self, key: str) -> None:
        try:
            self._inner.delete(self._tail_key(key))
        except Exception:
            # A tail left over costs storage and nothing else.
            logger.warning("tail_delete_failed key=%s", key, exc_info=True)

    def finish_parts(self, key: str, state: dict) -> None:
        if "enc" not in state:
            self._inner.finish_parts(key, state)
            return
        from app.core.storage_crypto import StorageCryptoError

        if state["enc"]["index"] != self._staged_header(state).chunk_count:
            raise StorageCryptoError("the upload is not all there")
        self._inner.finish_parts(key, state["inner"])
        self._drop_tail(key)

    def drop_parts(self, key: str, state: dict) -> None:
        if "enc" not in state:
            self._inner.drop_parts(key, state)
            return
        self._inner.drop_parts(key, state["inner"])
        self._drop_tail(key)


class _RangeReader(io.RawIOBase):
    """A stored object read a range at a time, as a caller seeks about it."""

    def __init__(self, backend: StorageBackend, key: str, size: int) -> None:
        self._backend, self._key, self._size, self._at = backend, key, size, 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._at

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._at, io.SEEK_END: self._size}
        self._at = max(0, base[whence] + offset)
        return self._at

    def readinto(self, buffer: Any) -> int:
        end = min(self._at + len(buffer), self._size)
        if end <= self._at:
            return 0
        blob = self._backend.open_readable(
            self._key, byte_range=f"bytes={self._at}-{end - 1}"
        )
        data = b"".join(blob.stream) if blob is not None and blob.stream else b""
        buffer[: len(data)] = data
        self._at += len(data)
        return len(data)


def open_seekable(backend: StorageBackend, key: str, size: int) -> BinaryIO | None:
    """``key``'s ``size`` bytes as a seekable file, ``None`` when it is
    missing: the file itself where the backend keeps one on disk, otherwise
    read a range at a time, so reading a few places in a large object fetches
    only those."""
    probe = backend.open_readable(key, byte_range="bytes=0-0")
    if probe is None:
        return None
    if probe.path is not None:
        return probe.path.open("rb")
    b"".join(probe.stream or ())
    return io.BufferedReader(_RangeReader(backend, key, size), buffer_size=_RANGE_READ)


def build_upload_response(
    blob: ReadableBlob,
    *,
    headers: dict[str, str] | None = None,
    media_type: str | None = None,
    filename: str | None = None,
) -> Response:
    """Adapt a :class:`ReadableBlob` into a Starlette response.

    Local blobs become a ``FileResponse`` (sendfile + range, media type inferred
    from the path as before). S3 blobs stream via ``StreamingResponse`` using the
    content-type recorded on the object, as ``206`` when the blob is the range a
    request asked for. ``filename`` forces an attachment
    download; otherwise the response is inline. The serve endpoints keep owning
    their security headers (CSP / nosniff / Content-Disposition) and pass them in.
    """
    headers = dict(headers or {})
    if blob.path is not None:
        if filename is not None:
            return FileResponse(
                blob.path,
                filename=filename,
                media_type=media_type or None,
                headers=headers,
            )
        return FileResponse(blob.path, media_type=media_type or None, headers=headers)

    media = media_type or blob.content_type or "application/octet-stream"
    if blob.content_length is not None and "Content-Length" not in headers:
        headers["Content-Length"] = str(blob.content_length)
    if filename is not None and "Content-Disposition" not in headers:
        headers["Content-Disposition"] = content_disposition_attachment(filename)
    headers.setdefault("Accept-Ranges", "bytes")
    if blob.content_range is not None:
        headers["Content-Range"] = blob.content_range
    return StreamingResponse(
        blob.stream or iter(()),
        status_code=206 if blob.content_range is not None else 200,
        media_type=media,
        headers=headers,
    )


_local_backends: dict[str, LocalFilesystemStorage] = {}
_s3_client: "BaseClient | None" = None


def reset_s3_client() -> None:
    """Drop the cached boto3 client so the next use rebuilds it.

    Called by :func:`app.services.storage_config.refresh_storage_config` when the
    resolved storage config changes (endpoint/region/credentials), so a runtime
    settings update takes effect without a restart.
    """
    global _s3_client
    _s3_client = None


def _backend_name() -> str:
    return current_storage_config().backend


def _local(prefix: str = "") -> LocalFilesystemStorage:
    backend = _local_backends.get(prefix)
    if backend is None:
        backend = LocalFilesystemStorage(prefix=prefix)
        _local_backends[prefix] = backend
    return backend


def build_s3_client(cfg: "ResolvedStorageConfig | None" = None) -> "BaseClient":
    """Construct a boto3 S3 client from a resolved storage config (uncached).

    Used by the request-path client cache (:func:`_get_s3_client`) and by the
    settings "test connection" path, which builds a one-off client from a
    candidate (possibly unsaved) config.
    """
    import boto3
    from botocore.config import Config

    if cfg is None:
        cfg = current_storage_config()

    config_kwargs: dict = {
        "signature_version": "s3v4",
        # botocore >=1.36 turns on "flexible checksums" by default
        # (request_checksum_calculation / response_checksum_validation =
        # "when_supported"), which sends extra checksum headers/trailers that many
        # S3-compatible stores (Garage, MinIO, R2, Ceph) don't implement — they
        # reject them with a signature/`AccessDenied` error, classically on
        # GetObject response validation. Restore the pre-1.36 behavior so we only
        # use checksums when an operation strictly requires them.
        "request_checksum_calculation": "when_required",
        "response_checksum_validation": "when_required",
    }
    if cfg.use_path_style:
        # Garage and most self-hosted stores require path-style addressing.
        config_kwargs["s3"] = {"addressing_style": "path"}

    client_kwargs: dict = {
        "region_name": cfg.region,
        "config": Config(**config_kwargs),
    }
    if cfg.endpoint_url:
        client_kwargs["endpoint_url"] = cfg.endpoint_url
    # Explicit keys when configured; otherwise boto3's ambient credential chain
    # (environment, shared config) supplies them.
    if cfg.access_key_id and cfg.secret_access_key:
        client_kwargs["aws_access_key_id"] = cfg.access_key_id
        client_kwargs["aws_secret_access_key"] = cfg.secret_access_key

    return boto3.client("s3", **client_kwargs)


def _get_s3_client() -> "BaseClient":
    global _s3_client
    if _s3_client is None:
        _s3_client = build_s3_client()
    return _s3_client


def _require_bucket() -> str:
    bucket = current_storage_config().bucket
    if not bucket:
        raise ValueError("STORAGE_BACKEND='s3' requires S3_BUCKET to be set")
    return bucket


def _make(prefix: str) -> StorageBackend:
    cfg = current_storage_config()
    name = cfg.backend
    if name == "local":
        return _local(prefix)
    if name == "s3":
        s3 = S3Storage(
            bucket=_require_bucket(),
            client=_get_s3_client(),
            prefix=prefix,
        )
        # Cutover window: serve blobs the backfill hasn't copied yet from local.
        if cfg.local_fallback:
            return DualReadStorage(primary=s3, fallback=_local(prefix))
        return s3
    raise ValueError(f"Unsupported STORAGE_BACKEND={name!r} (expected 'local' or 's3')")


def get_storage() -> StorageBackend:
    """Return the process-wide local backend.

    There is no *unscoped* S3 backend: all object-store content is guild-scoped,
    so S3 writes MUST go through :func:`get_guild_storage` (which namespaces keys
    under ``guild_<id>/``). Returning a root-prefixed S3 backend here would let a
    caller write objects at the bucket root, outside any guild namespace — so the
    S3 path raises instead. Identity media (avatars, icons) stays in Postgres, so
    there is no public-plane S3 caller that would need this.
    """
    if _backend_name() == "s3":
        raise NotImplementedError(
            "get_storage() has no unscoped S3 backend; use get_guild_storage(guild_id)"
        )
    return _make("")


def get_guild_storage(guild_id: int) -> StorageBackend:
    """Return a content-plane backend scoped to ``guild_id`` (the resolver).

    Both backends namespace the guild's blobs under ``guild_<id>/`` — the
    object-store twin of the schema-per-guild boundary (design §6). Local writes
    them under ``UPLOADS_DIR/guild_<id>/``. Every guild shares the one configured
    credential.

    Where storage is encrypted (``STORAGE_ENCRYPTION``, or keys left from when
    it was), the backend comes wrapped in :class:`EncryptedStorage`; where it
    is not — every deployment that leaves it unset — it is the backend itself.
    """
    from app.services.storage_keys import active_keyring

    backend = _make(f"guild_{int(guild_id)}/")
    keyring = active_keyring()
    if keyring is None:
        return backend
    return EncryptedStorage(backend, guild_id=guild_id, keyring=keyring)


#: What every evidence object's key starts with, in whichever community holds
#: it. The one kind of object that may be copied between communities.
EVIDENCE_KEY_PREFIX = "evidence-"


def _copy_across(src: StorageBackend, dst: StorageBackend, key: str) -> bool:
    """Copy ``key`` from one community's namespace to another's, as it is."""
    if isinstance(src, DualReadStorage) and isinstance(dst, DualReadStorage):
        if _copy_across(src._primary, dst._primary, key):
            return True
        # Not yet moved into the object store: copy what the fallback holds.
        blob = src._fallback.open_readable(key)
        if blob is None or blob.path is None:
            return False
        dst._primary.write(key, blob.path.read_bytes(), content_type=blob.content_type)
        return True
    if isinstance(src, S3Storage) and isinstance(dst, S3Storage):
        source = src._object_key(key)
        if not src._head(source):
            return False
        # Server-side: the bytes never pass through the application.
        dst._client.copy_object(
            Bucket=dst._bucket,
            Key=dst._object_key(key),
            CopySource={"Bucket": src._bucket, "Key": source},
        )
        return True
    if isinstance(src, LocalFilesystemStorage) and isinstance(
        dst, LocalFilesystemStorage
    ):
        source, target = src._safe_path(key), dst._safe_path(key)
        if source is None or target is None or not source.is_file():
            return False
        shutil.copyfile(source, target)
        return True
    raise TypeError("both communities are held by the same kind of store")


def copy_between_guilds(src_guild_id: int, dst_guild_id: int, key: str) -> bool:
    """Copy one evidence object from ``src_guild_id``'s namespace into
    ``dst_guild_id``'s under the same key, without reading it. Returns whether
    the source was there to copy.

    Evidence alone crosses: any other key is refused. What is copied is the
    stored form, already encrypted; re-wrapping its key for the destination is
    the caller's (``app.services.platform.evidence``).
    """
    if not key.startswith(EVIDENCE_KEY_PREFIX) or not is_flat_storage_key(key):
        raise ValueError("only an evidence object is copied between communities")
    if int(src_guild_id) == int(dst_guild_id):
        raise ValueError("source and destination are the same community")
    # The raw backends: evidence is never wrapped by EncryptedStorage.
    return _copy_across(
        _make(f"guild_{int(src_guild_id)}/"), _make(f"guild_{int(dst_guild_id)}/"), key
    )


def purge_guild_blobs(guild_id: int) -> int:
    """Remove all of a guild's stored blobs — called on guild deprovision.

    Both backends sweep the guild's ``guild_<id>/`` namespace in one pass (S3:
    batch object delete; local: remove the directory tree), so this is uniform
    and needs no per-file bookkeeping. Returns the number of objects removed.
    """
    return get_guild_storage(guild_id).delete_prefix()


def probe() -> None:
    """Reach the configured store once, raising if it cannot be reached.

    Synchronous (boto3 is), so callers on the event loop run it in a worker
    thread. ``head_bucket`` is the cheapest round trip that proves both the
    credential and the bucket; the local backend is proved by its directory
    existing and accepting a write.
    """
    cfg = current_storage_config()
    if cfg.backend == "s3":
        _get_s3_client().head_bucket(Bucket=_require_bucket())
        return
    directory = _local()._dir()
    if not os.access(directory, os.W_OK):
        raise OSError(f"{directory} is not writable")
