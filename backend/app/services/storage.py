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

import logging
import mimetypes
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Protocol, runtime_checkable
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

    def open_readable(self, key: str) -> ReadableBlob | None: ...

    # --- A file staged in parts (``app.services.resumable``) -----------------
    # ``state`` is the backend's own record of the parts, kept by the caller
    # between requests; each call returns it updated. ``stored`` in it counts
    # the bytes kept as parts, and ``tail`` those kept apart until the next.

    def start_parts(self, key: str, *, part_bytes: int) -> dict: ...

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
        # (a temp dir), and it streams rather than loading the file.
        shutil.copyfile(path, target)

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

    def resolve_readable(self, key: str) -> Path | None:
        """Filesystem path for a key, or None. Retained for local-only callers."""
        target = self._safe_path(key)
        if target is None or not target.is_file():
            return None
        return target

    def open_readable(self, key: str) -> ReadableBlob | None:
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

    def start_parts(self, key: str, *, part_bytes: int) -> dict:
        target = self._safe_path(key)
        if target is None:
            raise ValueError(f"Invalid storage key: {key!r}")
        target.write_bytes(b"")
        return {"stored": 0, "tail": 0, "part_bytes": part_bytes}

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

        Used to tear down a guild's content on deprovision. Refuses an empty
        prefix so it can never target the whole bucket. Returns the number of
        objects deleted.
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
        return deleted

    def exists(self, key: str) -> bool:
        return self._head(self._object_key(key))

    def open_readable(self, key: str) -> ReadableBlob | None:
        from botocore.exceptions import ClientError

        try:
            obj = self._client.get_object(
                Bucket=self._bucket, Key=self._object_key(key)
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _S3_MISSING_CODES:
                return None
            raise
        return ReadableBlob(
            stream=obj["Body"].iter_chunks(chunk_size=_STREAM_CHUNK),
            content_type=obj.get("ContentType"),
            content_length=obj.get("ContentLength"),
        )

    def _tail_key(self, key: str) -> str:
        return self._object_key(f"{Path(key).name}-tail")

    def start_parts(self, key: str, *, part_bytes: int) -> dict:
        upload = self._client.create_multipart_upload(
            Bucket=self._bucket, Key=self._object_key(key)
        )
        return {
            "upload_id": upload["UploadId"],
            "parts": [],
            "stored": 0,
            "tail": 0,
            "part_bytes": part_bytes,
        }

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

    def open_readable(self, key: str) -> ReadableBlob | None:
        # The whole point of the fallback window is "keep serving during the
        # cutover." A clean miss (None) falls through to local; so does an S3
        # *error* (auth/signature/transient) — we log it loudly so a real
        # misconfiguration is still visible, but a half-migrated deployment keeps
        # serving from local instead of 500ing. Once the backfill is verified and
        # S3 reads are healthy, turn S3_LOCAL_FALLBACK off.
        try:
            blob = self._primary.open_readable(key)
        except Exception:
            logger.warning(
                "S3 read failed for %r; serving from local fallback "
                "(S3_LOCAL_FALLBACK on). Resolve the S3 error before disabling "
                "fallback.",
                key,
                exc_info=True,
            )
            blob = None
        return blob or self._fallback.open_readable(key)

    def start_parts(self, key: str, *, part_bytes: int) -> dict:
        return self._primary.start_parts(key, part_bytes=part_bytes)

    def add_part(self, key: str, state: dict, data: bytes) -> dict:
        return self._primary.add_part(key, state, data)

    def keep_tail(self, key: str, state: dict, data: bytes) -> dict:
        return self._primary.keep_tail(key, state, data)

    def take_tail(self, key: str, state: dict) -> tuple[bytes, dict]:
        return self._primary.take_tail(key, state)

    def finish_parts(self, key: str, state: dict) -> None:
        self._primary.finish_parts(key, state)

    def drop_parts(self, key: str, state: dict) -> None:
        self._primary.drop_parts(key, state)

    def presign_get(
        self, key: str, *, ttl: int, filename: str | None = None
    ) -> str | None:
        # Only S3 can sign; if the object is still local-only, return None so the
        # caller proxy-serves it instead.
        if self._primary.exists(key):
            return self._primary.presign_get(key, ttl=ttl, filename=filename)
        return None


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
    content-type recorded on the object. ``filename`` forces an attachment
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
    return StreamingResponse(blob.stream or iter(()), media_type=media, headers=headers)


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
    """
    return _make(f"guild_{int(guild_id)}/")


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
    return _copy_across(
        get_guild_storage(src_guild_id), get_guild_storage(dst_guild_id), key
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
