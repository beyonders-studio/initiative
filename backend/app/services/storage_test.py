"""Unit tests for the storage backends (storage rebuild).

The local-backend tests are pure filesystem (no DB). The S3 tests drive
``S3Storage`` against an in-memory fake boto3 client — deterministic, no network
or object store needed — verifying the guild-prefix keying, the basename guard,
SSE params, and the serve adapter. Integration against a real S3-compatible
endpoint (e.g. a Garage instance) is left to manual/CI runs.
"""

import pytest
from botocore.exceptions import ClientError
from fastapi.responses import FileResponse, StreamingResponse

from app.services import storage as storage_module
from app.services import storage_config
from app.services.storage import (
    DualReadStorage,
    LocalFilesystemStorage,
    ReadableBlob,
    S3Storage,
    StorageBackend,
    build_upload_response,
    requested_range,
    get_guild_storage,
    get_storage,
)


@pytest.fixture(autouse=True)
def _reset_storage_config_cache():
    """Drop the resolved-config snapshot around each test so the resolver falls
    back to env ``settings`` (which these tests monkeypatch). Without this a
    concurrent test that populated the cache via ``refresh_storage_config`` would
    make the resolver ignore the patched env backend."""
    storage_config.reset_for_tests()
    yield
    storage_config.reset_for_tests()


def test_write_read_roundtrip(tmp_path):
    storage = LocalFilesystemStorage(base_dir=str(tmp_path))
    storage.write("abc.txt", b"hello")
    resolved = storage.resolve_readable("abc.txt")
    assert resolved is not None
    assert resolved.read_bytes() == b"hello"
    assert storage.exists("abc.txt") is True


def test_delete(tmp_path):
    storage = LocalFilesystemStorage(base_dir=str(tmp_path))
    storage.write("x.bin", b"data")
    assert storage.delete("x.bin") is True
    assert storage.exists("x.bin") is False
    # Deleting a missing key is a no-op, reported as False.
    assert storage.delete("x.bin") is False


def test_copy(tmp_path):
    storage = LocalFilesystemStorage(base_dir=str(tmp_path))
    storage.write("src.bin", b"payload")
    assert storage.copy("src.bin", "dst.bin") is True
    resolved = storage.resolve_readable("dst.bin")
    assert resolved is not None and resolved.read_bytes() == b"payload"
    # Copying a missing source fails cleanly.
    assert storage.copy("missing.bin", "dst2.bin") is False


def test_resolve_missing_returns_none(tmp_path):
    storage = LocalFilesystemStorage(base_dir=str(tmp_path))
    assert storage.resolve_readable("nope.txt") is None


def test_path_traversal_is_contained(tmp_path):
    base = tmp_path / "uploads"
    storage = LocalFilesystemStorage(base_dir=str(base))
    # A sentinel that lives OUTSIDE the base dir must stay unreachable.
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"secret")
    # Keys are reduced to a basename, so a traversal attempt can never escape.
    assert storage.resolve_readable("../secret.txt") is None
    assert storage.exists("../secret.txt") is False


def test_empty_key_is_rejected(tmp_path):
    storage = LocalFilesystemStorage(base_dir=str(tmp_path))
    with pytest.raises(ValueError):
        storage.write("", b"data")
    assert storage.resolve_readable("") is None


def test_get_storage_returns_local_singleton():
    backend = get_storage()
    assert isinstance(backend, StorageBackend)
    # Process-wide singleton.
    assert get_storage() is backend


# --- S3Storage (in-memory fake boto3 client) ---------------------------------


class _FakeBody:
    """Mimics the boto3 StreamingBody.iter_chunks() interface."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data

    def iter_chunks(self, chunk_size: int = 65536):
        for i in range(0, len(self._data), chunk_size):
            yield self._data[i : i + chunk_size]


class FakeS3Client:
    """Minimal in-memory stand-in for a boto3 S3 client."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict] = {}
        self.presigned: list[tuple] = []
        # Keys delete_objects should report as failed (not actually removed).
        self.delete_errors: set[str] = set()
        self.parts: dict[int, bytes] = {}
        self.multipart_open = False

    @staticmethod
    def _missing(op: str) -> ClientError:
        return ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, op)

    def put_object(self, *, Bucket, Key, Body, **extra):
        self.objects[(Bucket, Key)] = {"Body": Body, "extra": extra}
        return {}

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None):
        with open(Filename, "rb") as handle:
            self.put_object(
                Bucket=Bucket, Key=Key, Body=handle.read(), **(ExtraArgs or {})
            )

    def head_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise self._missing("HeadObject")
        return {}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop((Bucket, Key), None)
        return {}

    def copy_object(self, *, Bucket, Key, CopySource, **extra):
        src = (CopySource["Bucket"], CopySource["Key"])
        if src not in self.objects:
            raise self._missing("CopyObject")
        self.objects[(Bucket, Key)] = {
            "Body": self.objects[src]["Body"],
            "extra": extra,
        }
        return {}

    def get_object(self, *, Bucket, Key, Range=None):
        if (Bucket, Key) not in self.objects:
            raise self._missing("GetObject")
        rec = self.objects[(Bucket, Key)]
        body = rec["Body"]
        answer = {"ContentType": rec["extra"].get("ContentType")}
        if Range is not None:
            first, _, last = Range.removeprefix("bytes=").partition("-")
            start = int(first) if first else len(body) - int(last)
            end = min(int(last), len(body) - 1) if first and last else len(body) - 1
            if start >= len(body):
                raise ClientError(
                    {"Error": {"Code": "InvalidRange", "Message": "bad"}}, "GetObject"
                )
            answer["ContentRange"] = f"bytes {start}-{end}/{len(body)}"
            body = body[start : end + 1]
        return {**answer, "Body": _FakeBody(body), "ContentLength": len(body)}

    def create_multipart_upload(self, *, Bucket, Key):
        self.parts, self.multipart_open = {}, True
        return {"UploadId": "up-1"}

    def upload_part(self, *, Bucket, Key, UploadId, PartNumber, Body):
        assert UploadId == "up-1" and self.multipart_open
        self.parts[PartNumber] = Body
        return {"ETag": f"etag-{PartNumber}"}

    def complete_multipart_upload(self, *, Bucket, Key, UploadId, MultipartUpload):
        if not self.multipart_open:
            raise ClientError(
                {"Error": {"Code": "NoSuchUpload", "Message": "gone"}},
                "CompleteMultipartUpload",
            )
        numbers = [part["PartNumber"] for part in MultipartUpload["Parts"]]
        self.objects[(Bucket, Key)] = {
            "Body": b"".join(self.parts[n] for n in numbers),
            "extra": {},
        }
        self.multipart_open = False
        return {}

    def abort_multipart_upload(self, *, Bucket, Key, UploadId):
        self.multipart_open = False
        return {}

    def generate_presigned_url(self, op, *, Params, ExpiresIn):
        self.presigned.append((op, Params, ExpiresIn))
        disp = Params.get("ResponseContentDisposition", "")
        return f"https://s3.test/{Params['Key']}?exp={ExpiresIn}&disp={disp}"

    def list_objects_v2(self, *, Bucket, Prefix, ContinuationToken=None):
        keys = [k for (b, k) in self.objects if b == Bucket and k.startswith(Prefix)]
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}

    def delete_objects(self, *, Bucket, Delete):
        errors = []
        for obj in Delete["Objects"]:
            key = obj["Key"]
            if key in self.delete_errors:
                errors.append({"Key": key, "Code": "AccessDenied", "Message": "denied"})
                continue
            self.objects.pop((Bucket, key), None)
        return {"Errors": errors} if errors else {}


def _s3(prefix="guild_7/"):
    client = FakeS3Client()
    return client, S3Storage(bucket="bucket", client=client, prefix=prefix)


def test_s3_write_applies_guild_prefix_and_content_type():
    client, storage = _s3()
    storage.write("abc.png", b"img", content_type="image/png")
    # Keyed under the resolver-supplied guild prefix.
    assert ("bucket", "guild_7/abc.png") in client.objects
    # The content type is the only parameter sent; encryption is the bucket's.
    assert client.objects[("bucket", "guild_7/abc.png")]["extra"] == {
        "ContentType": "image/png"
    }


def test_s3_key_reduces_to_basename():
    # A traversal-style key can never escape the guild prefix.
    client, storage = _s3()
    storage.write("../../etc/passwd", b"x")
    assert ("bucket", "guild_7/passwd") in client.objects


def test_s3_exists_and_delete():
    client, storage = _s3()
    assert storage.exists("a.txt") is False
    storage.write("a.txt", b"hi")
    assert storage.exists("a.txt") is True
    assert storage.delete("a.txt") is True
    assert storage.exists("a.txt") is False
    # Deleting a missing key reports False (parity with the local backend).
    assert storage.delete("a.txt") is False


def test_s3_copy_same_namespace():
    client, storage = _s3()
    storage.write("src.bin", b"payload")
    assert storage.copy("src.bin", "dst.bin") is True
    assert client.objects[("bucket", "guild_7/dst.bin")]["extra"] == {}
    # Copying a missing source fails cleanly.
    assert storage.copy("missing.bin", "dst2.bin") is False


def test_s3_open_readable_round_trip():
    _, storage = _s3()
    storage.write("doc.pdf", b"hello world", content_type="application/pdf")
    blob = storage.open_readable("doc.pdf")
    assert blob is not None
    assert blob.path is None
    assert blob.content_type == "application/pdf"
    assert blob.content_length == len(b"hello world")
    assert b"".join(blob.stream) == b"hello world"


def test_s3_stages_a_file_in_parts_with_a_tail_between_requests():
    client, storage = _s3()
    state = storage.start_parts("resumable-a", part_bytes=8)

    state = storage.add_part("resumable-a", state, b"first---")
    # A request's last few bytes wait apart, below S3's least part.
    state = storage.keep_tail("resumable-a", state, b"sec")
    assert ("bucket", "guild_7/resumable-a-tail") in client.objects
    tail, state = storage.take_tail("resumable-a", state)
    state = storage.add_part("resumable-a", state, tail + b"ond")
    storage.finish_parts("resumable-a", state)

    blob = storage.open_readable("resumable-a")
    assert b"".join(blob.stream) == b"first---second"
    assert ("bucket", "guild_7/resumable-a-tail") not in client.objects
    assert state["stored"] == 14


def test_s3_reads_back_only_the_tail_that_was_recorded():
    """A tail written by a request whose record did not land starts with the
    one recorded before it."""
    _, storage = _s3()
    state = storage.start_parts("resumable-c", part_bytes=8)
    recorded = storage.keep_tail("resumable-c", state, b"abc")
    storage.keep_tail("resumable-c", recorded, b"abcdef")

    tail, _ = storage.take_tail("resumable-c", recorded)

    assert tail == b"abc"


def test_s3_finishing_twice_finds_the_object_there():
    _, storage = _s3()
    state = storage.start_parts("resumable-d", part_bytes=8)
    state = storage.add_part("resumable-d", state, b"whole")
    storage.finish_parts("resumable-d", state)

    storage.finish_parts("resumable-d", state)

    assert b"".join(storage.open_readable("resumable-d").stream) == b"whole"


def test_s3_drops_a_staged_file_whole():
    client, storage = _s3()
    state = storage.start_parts("resumable-b", part_bytes=8)
    state = storage.keep_tail("resumable-b", state, b"abc")

    storage.drop_parts("resumable-b", state)

    assert client.multipart_open is False
    assert not client.objects


def test_s3_open_readable_reads_the_range_asked_for():
    _, storage = _s3()
    storage.write("clip.mp4", b"hello world", content_type="video/mp4")

    part = storage.open_readable("clip.mp4", byte_range="bytes=6-")
    assert b"".join(part.stream) == b"world"
    assert (part.content_length, part.content_range) == (5, "bytes 6-10/11")
    # A range past the end is answered with the whole object.
    whole = storage.open_readable("clip.mp4", byte_range="bytes=50-")
    assert b"".join(whole.stream) == b"hello world"
    assert whole.content_range is None


@pytest.mark.parametrize(
    ("header", "kept"),
    [
        ("bytes=0-499", True),
        ("bytes=500-", True),
        ("bytes=-500", True),
        ("bytes=0-1,5-9", False),
        ("bytes=9-1", False),
        ("bytes=-", False),
        ("items=0-1", False),
        ("bytes=٠-1", False),
        ("bytes=" + "9" * 4301 + "-9", False),
        (None, False),
    ],
)
def test_one_range_of_bytes_is_honoured(header, kept):
    assert requested_range(header) == (header if kept else None)


def test_build_upload_response_stream_answers_a_range_partially():
    blob = ReadableBlob(
        stream=iter([b"world"]),
        content_type="video/mp4",
        content_length=5,
        content_range="bytes 6-10/11",
    )
    resp = build_upload_response(blob)
    assert resp.status_code == 206
    assert resp.headers["Content-Range"] == "bytes 6-10/11"
    assert resp.headers["Accept-Ranges"] == "bytes"


def test_s3_open_readable_missing_returns_none():
    _, storage = _s3()
    assert storage.open_readable("nope.bin") is None


def test_s3_presign_get_includes_key_and_filename():
    client, storage = _s3()
    url = storage.presign_get("file.zip", ttl=90, filename="report.zip")
    assert "guild_7/file.zip" in url
    op, params, ttl = client.presigned[0]
    assert op == "get_object"
    assert ttl == 90
    assert "report.zip" in params["ResponseContentDisposition"]


def test_build_upload_response_local_is_file_response(tmp_path):
    f = tmp_path / "x.png"
    f.write_bytes(b"img")
    resp = build_upload_response(ReadableBlob(path=f), media_type="image/png")
    assert isinstance(resp, FileResponse)


def test_build_upload_response_stream_sets_type_and_length():
    blob = ReadableBlob(
        stream=iter([b"chunk"]), content_type="image/png", content_length=5
    )
    resp = build_upload_response(blob)
    assert isinstance(resp, StreamingResponse)
    assert resp.media_type == "image/png"
    assert resp.headers["Content-Length"] == "5"


def test_build_upload_response_stream_attachment_disposition():
    blob = ReadableBlob(stream=iter([b"z"]), content_type="application/pdf")
    resp = build_upload_response(blob, filename="r.pdf")
    assert isinstance(resp, StreamingResponse)
    assert 'attachment; filename="r.pdf"' in resp.headers["Content-Disposition"]


def test_build_upload_response_escapes_quote_in_filename():
    # A filename with a double-quote must not break out of the header value;
    # it falls back to RFC 5987 filename*= encoding.
    blob = ReadableBlob(stream=iter([b"z"]), content_type="application/pdf")
    resp = build_upload_response(blob, filename='report"final".pdf')
    disposition = resp.headers["Content-Disposition"]
    assert "filename*=utf-8''" in disposition
    assert '"final"' not in disposition  # the raw quote did not survive verbatim


def test_resolver_namespaces_by_guild_for_s3(monkeypatch):
    monkeypatch.setattr(storage_module.settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(storage_module.settings, "S3_BUCKET", "bucket")
    monkeypatch.setattr(storage_module, "_get_s3_client", lambda: FakeS3Client())

    scoped = get_guild_storage(42)
    assert isinstance(scoped, S3Storage)
    assert scoped._prefix == "guild_42/"
    assert scoped._bucket == "bucket"
    # There is no unscoped S3 backend (it would write at the bucket root, outside
    # any guild namespace), so get_storage() refuses under s3.
    with pytest.raises(NotImplementedError):
        get_storage()


def test_resolver_requires_bucket_for_s3(monkeypatch):
    monkeypatch.setattr(storage_module.settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(storage_module.settings, "S3_BUCKET", None)
    with pytest.raises(ValueError, match="S3_BUCKET"):
        get_guild_storage(1)


def test_resolver_local_honors_guild_prefix():
    # Default backend is local; it now namespaces by guild like S3.
    backend = get_guild_storage(99)
    assert isinstance(backend, LocalFilesystemStorage)
    assert backend._prefix == "guild_99/"


# --- S3Storage.delete_prefix -------------------------------------------------


def test_s3_delete_prefix_sweeps_namespace():
    client, storage = _s3()
    storage.write("a.bin", b"1")
    storage.write("b.bin", b"2")
    # An object in a *different* guild's namespace must survive.
    other = S3Storage(bucket="bucket", client=client, prefix="guild_8/")
    other.write("c.bin", b"3")

    removed = storage.delete_prefix()
    assert removed == 2
    assert ("bucket", "guild_7/a.bin") not in client.objects
    assert ("bucket", "guild_7/b.bin") not in client.objects
    assert ("bucket", "guild_8/c.bin") in client.objects  # untouched


def test_s3_delete_prefix_refuses_empty_prefix():
    _, storage = _s3(prefix="")
    with pytest.raises(ValueError, match="empty prefix"):
        storage.delete_prefix()


def test_s3_delete_prefix_counts_only_successful_deletes():
    client, storage = _s3()
    storage.write("a.bin", b"1")
    storage.write("b.bin", b"2")
    # Simulate S3 reporting one key as failed (object lock, perms, …).
    client.delete_errors.add("guild_7/b.bin")
    removed = storage.delete_prefix()
    # Only the successful delete is counted; the failed object remains.
    assert removed == 1
    assert ("bucket", "guild_7/b.bin") in client.objects
    assert ("bucket", "guild_7/a.bin") not in client.objects


# --- LocalFilesystemStorage prefix + delete_prefix ---------------------------


def test_local_prefix_writes_under_guild_dir(tmp_path):
    storage = LocalFilesystemStorage(base_dir=str(tmp_path), prefix="guild_3/")
    storage.write("img.png", b"data")
    assert (tmp_path / "guild_3" / "img.png").read_bytes() == b"data"
    # Round-trips through the prefixed namespace, with metadata consistent with S3.
    blob = storage.open_readable("img.png")
    assert blob.path == tmp_path / "guild_3" / "img.png"
    assert blob.content_type == "image/png"  # derived from extension
    assert blob.content_length == 4


def test_local_delete_prefix_removes_dir_and_counts(tmp_path):
    storage = LocalFilesystemStorage(base_dir=str(tmp_path), prefix="guild_3/")
    storage.write("a.png", b"1")
    storage.write("b.png", b"2")
    removed = storage.delete_prefix()
    assert removed == 2
    assert not (tmp_path / "guild_3").exists()
    # Missing dir -> 0, no error.
    assert storage.delete_prefix() == 0


def test_local_delete_prefix_refuses_empty_prefix(tmp_path):
    storage = LocalFilesystemStorage(base_dir=str(tmp_path))  # prefix=""
    with pytest.raises(ValueError, match="empty prefix"):
        storage.delete_prefix()


def test_purge_guild_blobs_local(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_module.settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(storage_module.settings, "UPLOADS_DIR", str(tmp_path))
    storage_module._local_backends.clear()
    get_guild_storage(5).write("x.png", b"data")
    assert (tmp_path / "guild_5" / "x.png").exists()
    removed = storage_module.purge_guild_blobs(5)
    assert removed == 1
    assert not (tmp_path / "guild_5").exists()
    storage_module._local_backends.clear()


# --- DualReadStorage (local->S3 cutover fallback) ----------------------------


def _dual(tmp_path):
    client = FakeS3Client()
    s3 = S3Storage(bucket="bucket", client=client, prefix="guild_7/")
    local = LocalFilesystemStorage(base_dir=str(tmp_path), prefix="guild_7/")
    return client, s3, local, DualReadStorage(primary=s3, fallback=local)


def test_dualread_write_goes_to_primary_only(tmp_path):
    client, _, local, dual = _dual(tmp_path)
    dual.write("x.png", b"data", content_type="image/png")
    assert ("bucket", "guild_7/x.png") in client.objects
    assert not (tmp_path / "guild_7" / "x.png").exists()


def test_dualread_read_falls_back_to_local_then_prefers_s3(tmp_path):
    _, s3, local, dual = _dual(tmp_path)
    # Un-backfilled blob: only on local -> served from local (path).
    local.write("old.png", b"local-bytes")
    blob = dual.open_readable("old.png")
    assert blob is not None and blob.path is not None
    assert blob.path.read_bytes() == b"local-bytes"
    # Backfilled blob: present in S3 -> served from S3 (stream) even if absent local.
    s3.write("new.png", b"s3-bytes", content_type="image/png")
    blob2 = dual.open_readable("new.png")
    assert blob2 is not None and blob2.stream is not None
    assert b"".join(blob2.stream) == b"s3-bytes"


def test_dualread_read_falls_back_to_local_on_s3_error(tmp_path):
    """During cutover (S3_LOCAL_FALLBACK on), an S3 read *error* — not just a
    clean miss — must fall back to local rather than bubble up a 500. The blob
    still exists locally, so the page keeps working while the S3 problem (auth,
    signature, etc.) is fixed."""
    _, s3, local, dual = _dual(tmp_path)
    local.write("doc.svg", b"local-bytes")

    def _boom(*, Bucket, Key):
        raise ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Invalid signature"}},
            "GetObject",
        )

    s3._client.get_object = _boom  # primary read raises instead of missing

    blob = dual.open_readable("doc.svg")
    assert blob is not None and blob.path is not None
    assert blob.path.read_bytes() == b"local-bytes"


def test_dualread_exists_checks_both(tmp_path):
    _, s3, local, dual = _dual(tmp_path)
    local.write("a", b"1")
    s3.write("b", b"2")
    assert dual.exists("a") is True
    assert dual.exists("b") is True
    assert dual.exists("missing") is False


def test_dualread_delete_removes_from_both(tmp_path):
    _, s3, local, dual = _dual(tmp_path)
    s3.write("d", b"1")
    local.write("d", b"1")
    assert dual.delete("d") is True
    assert dual.exists("d") is False


def test_dualread_delete_prefix_sums_both(tmp_path):
    _, s3, local, dual = _dual(tmp_path)
    s3.write("a", b"1")
    s3.write("b", b"2")
    local.write("c", b"3")
    assert dual.delete_prefix() == 3


def test_dualread_copy_cross_store(tmp_path):
    client, _, local, dual = _dual(tmp_path)
    # Source only on local (not yet backfilled): copy reads local, writes to S3.
    local.write("src.png", b"payload")
    assert dual.copy("src.png", "dst.png") is True
    obj = client.objects[("bucket", "guild_7/dst.png")]
    # Content-type recovered from the extension so it isn't served as octet-stream.
    assert obj["extra"] == {"ContentType": "image/png"}


# --- copy_between_guilds -----------------------------------------------------


def test_evidence_copies_between_communities_on_s3(monkeypatch):
    client = FakeS3Client()
    monkeypatch.setattr(storage_module.settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(storage_module.settings, "S3_BUCKET", "bucket")
    monkeypatch.setattr(storage_module, "_get_s3_client", lambda: client)
    get_guild_storage(3).write("evidence-abc.iev", b"sealed")

    assert storage_module.copy_between_guilds(3, 9, "evidence-abc.iev") is True
    # A server-side copy into the other community's namespace, bytes as they were.
    assert client.objects[("bucket", "guild_9/evidence-abc.iev")]["Body"] == b"sealed"
    assert storage_module.copy_between_guilds(3, 9, "evidence-gone.iev") is False


def test_evidence_copies_between_communities_locally(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_module.settings, "UPLOADS_DIR", str(tmp_path))
    get_guild_storage(3).write("evidence-abc.iev", b"sealed")

    assert storage_module.copy_between_guilds(3, 9, "evidence-abc.iev") is True
    assert (tmp_path / "guild_9" / "evidence-abc.iev").read_bytes() == b"sealed"


@pytest.mark.parametrize("key", ["photo.png", "../evidence-x.iev", "dir/evidence-x"])
def test_nothing_but_evidence_crosses(key):
    with pytest.raises(ValueError):
        storage_module.copy_between_guilds(3, 9, key)


def test_evidence_does_not_copy_onto_itself():
    with pytest.raises(ValueError):
        storage_module.copy_between_guilds(3, 3, "evidence-abc.iev")
