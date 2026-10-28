"""Encrypted storage: the wrapper over a real local backend and the fake S3
client, with an in-memory key store. No database."""

import base64
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.core import storage_crypto
from app.core.config import settings
from app.services import storage as storage_module
from app.services import storage_config, storage_keys
from app.services.storage import (
    EVIDENCE_KEY_PREFIX,
    EncryptedStorage,
    LocalFilesystemStorage,
    ReadableBlob,
    S3Storage,
    get_guild_storage,
)
from app.services.storage_keys import Keyring, KeyRow, KmsRoot, LocalRoot
from app.services.storage_test import FakeS3Client

GUILD = 7
CHUNK = storage_crypto.CHUNK_SIZE


class MemoryKeyStore:
    def __init__(self) -> None:
        self.rows: dict[int, KeyRow] = {}
        self.reopened: list[int] = []

    def get(self, guild_id: int) -> KeyRow | None:
        return self.rows.get(guild_id)

    def reopen(self, guild_id: int) -> None:
        self.reopened.append(guild_id)

    def add(self, guild_id: int, columns: dict[str, str]) -> KeyRow:
        self.rows.setdefault(
            guild_id,
            KeyRow(
                guild_id=guild_id,
                generation=1,
                local_sealed=columns.get("local_sealed"),
                kms_sealed=columns.get("kms_sealed"),
                kms_key=columns.get("kms_key"),
            ),
        )
        return self.rows[guild_id]


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    storage_config.reset_for_tests()
    yield
    storage_keys.use_keyring(None)
    storage_config.reset_for_tests()


@pytest.fixture
def keys() -> MemoryKeyStore:
    return MemoryKeyStore()


@pytest.fixture
def keyring(keys: MemoryKeyStore) -> Keyring:
    return Keyring(keys, LocalRoot())


def _local(
    tmp_path: Path, keyring: Keyring, guild_id: int = GUILD
) -> tuple[LocalFilesystemStorage, EncryptedStorage]:
    inner = LocalFilesystemStorage(base_dir=str(tmp_path), prefix=f"guild_{guild_id}/")
    return inner, EncryptedStorage(inner, guild_id=guild_id, keyring=keyring)


def _read(blob: ReadableBlob | None) -> bytes:
    assert blob is not None
    if blob.path is not None:
        return blob.path.read_bytes()
    return b"".join(blob.stream)


def test_an_object_is_stored_encrypted_and_reads_back(tmp_path, keyring):
    inner, storage = _local(tmp_path, keyring)
    plaintext = os.urandom(3 * CHUNK + 11)
    storage.write("a.bin", plaintext, content_type="application/pdf")

    stored = inner.resolve_readable("a.bin").read_bytes()
    assert stored.startswith(storage_crypto.MAGIC)
    assert plaintext not in stored
    blob = storage.open_readable("a.bin")
    assert blob.path is None
    assert blob.content_length == len(plaintext)
    assert _read(blob) == plaintext


def test_a_range_reads_only_what_it_asks(tmp_path, keyring):
    _, storage = _local(tmp_path, keyring)
    plaintext = os.urandom(4 * CHUNK)
    storage.write("v.mp4", plaintext)

    blob = storage.open_readable(
        "v.mp4", byte_range=f"bytes={CHUNK - 3}-{2 * CHUNK + 4}"
    )
    assert _read(blob) == plaintext[CHUNK - 3 : 2 * CHUNK + 5]
    assert blob.content_range == f"bytes {CHUNK - 3}-{2 * CHUNK + 4}/{len(plaintext)}"
    assert blob.content_length == CHUNK + 8


def test_a_file_on_disk_is_encrypted_without_holding_it(tmp_path, keyring):
    _, storage = _local(tmp_path / "store", keyring)
    source = tmp_path / "export.zip"
    source.write_bytes(os.urandom(2 * CHUNK + 1))
    storage.write_file("export.zip", source)
    assert _read(storage.open_readable("export.zip")) == source.read_bytes()


def test_an_object_stored_before_encryption_reads_as_it_is(tmp_path, keyring):
    inner, storage = _local(tmp_path, keyring)
    inner.write("old.txt", b"written in the clear")
    assert _read(storage.open_readable("old.txt")) == b"written in the clear"
    assert storage.is_encrypted("old.txt") is False

    assert storage.encrypt_in_place("old.txt") is True
    assert storage.is_encrypted("old.txt") is True
    assert _read(storage.open_readable("old.txt")) == b"written in the clear"
    assert storage.encrypt_in_place("old.txt") is False


def test_evidence_is_left_as_it_is(tmp_path, keyring):
    inner, storage = _local(tmp_path, keyring)
    key = f"{EVIDENCE_KEY_PREFIX}abc"
    storage.write(key, b"already sealed by blob_crypto")
    assert inner.resolve_readable(key).read_bytes() == b"already sealed by blob_crypto"
    assert storage.encrypt_in_place(key) is False


def test_another_community_cannot_open_a_copy(tmp_path, keyring):
    inner, storage = _local(tmp_path, keyring)
    storage.write("x.bin", b"ours")
    other_inner, other = _local(tmp_path, keyring, guild_id=GUILD + 1)
    other_inner.write("x.bin", inner.resolve_readable("x.bin").read_bytes())
    with pytest.raises(storage_crypto.StorageCryptoError):
        _read(other.open_readable("x.bin"))


def test_a_destroyed_key_leaves_nothing_readable(tmp_path, keys, keyring):
    _, storage = _local(tmp_path, keyring)
    storage.write("x.bin", b"gone with the key")
    del keys.rows[GUILD]
    keyring.forget(GUILD)
    with pytest.raises(storage_crypto.StorageCryptoError):
        storage.open_readable("x.bin")


def test_a_copy_within_the_community_stays_readable(tmp_path, keyring):
    _, storage = _local(tmp_path, keyring)
    storage.write("a.bin", b"duplicated")
    assert storage.copy("a.bin", "b.bin") is True
    assert _read(storage.open_readable("b.bin")) == b"duplicated"


def test_nothing_is_signed_for_direct_download(tmp_path, keyring):
    _, storage = _local(tmp_path, keyring)
    assert storage.presign_get("a.bin", ttl=60) is None


def _upload(
    storage: EncryptedStorage, key: str, plaintext: bytes, *, request_sizes: list[int]
) -> dict:
    """Drive the part methods the way ``app.services.resumable`` does."""
    state = storage.start_parts(key, part_bytes=CHUNK + 1, length=len(plaintext))
    at = 0
    for size in request_sizes:
        tail, state = storage.take_tail(key, state)
        buffer = bytearray(tail) + plaintext[at : at + size]
        at += size
        part = state["part_bytes"]
        while len(buffer) >= part and state["stored"] + part < len(plaintext):
            state = storage.add_part(key, state, bytes(buffer[:part]))
            del buffer[:part]
        if state["stored"] + len(buffer) == len(plaintext):
            if buffer:
                state = storage.add_part(key, state, bytes(buffer))
            storage.finish_parts(key, state)
            return state
        state = storage.keep_tail(key, state, bytes(buffer))
    raise AssertionError("the upload never finished")


def test_a_file_arriving_in_parts_is_encrypted_tail_and_all(tmp_path, keyring):
    inner, storage = _local(tmp_path, keyring)
    plaintext = os.urandom(5 * CHUNK + 123)
    state = _upload(
        storage,
        "resumable-u",
        plaintext,
        request_sizes=[CHUNK // 3, 2 * CHUNK, 3 * CHUNK + 1000],
    )

    assert state["part_bytes"] % CHUNK == 0
    assert not inner.exists("resumable-u-etail")
    assert (
        inner.resolve_readable("resumable-u")
        .read_bytes()
        .startswith(storage_crypto.MAGIC)
    )
    assert _read(storage.open_readable("resumable-u")) == plaintext


def test_the_kept_tail_is_never_stored_in_the_clear(tmp_path, keyring):
    inner, storage = _local(tmp_path, keyring)
    plaintext = b"a tail that waits between requests" * 10
    state = storage.start_parts(
        "resumable-t", part_bytes=CHUNK, length=len(plaintext) + 1
    )
    state = storage.keep_tail("resumable-t", state, plaintext)
    kept = inner.resolve_readable("resumable-t-etail").read_bytes()
    assert plaintext not in kept
    tail, _ = storage.take_tail("resumable-t", state)
    assert tail == plaintext


def test_an_empty_upload_is_finished_and_authenticated(tmp_path, keyring):
    _, storage = _local(tmp_path, keyring)
    state = storage.start_parts("resumable-e", part_bytes=CHUNK, length=0)
    storage.finish_parts("resumable-e", state)
    assert _read(storage.open_readable("resumable-e")) == b""


def test_an_upload_begun_in_the_clear_finishes_in_the_clear(tmp_path, keyring):
    inner, storage = _local(tmp_path, keyring)
    state = inner.start_parts("resumable-o", part_bytes=8)
    state = storage.add_part("resumable-o", state, b"12345678")
    storage.finish_parts("resumable-o", state)
    assert inner.resolve_readable("resumable-o").read_bytes() == b"12345678"


def test_parts_on_s3_with_a_tail_between_requests(keyring):
    client = FakeS3Client()
    inner = S3Storage(bucket="bucket", client=client, prefix=f"guild_{GUILD}/")
    storage = EncryptedStorage(inner, guild_id=GUILD, keyring=keyring)
    plaintext = os.urandom(3 * CHUNK + 77)
    _upload(
        storage, "resumable-s", plaintext, request_sizes=[CHUNK + 5, CHUNK, CHUNK + 72]
    )

    assert ("bucket", f"guild_{GUILD}/resumable-s-etail") not in client.objects
    assert _read(storage.open_readable("resumable-s")) == plaintext
    blob = storage.open_readable("resumable-s", byte_range="bytes=-50")
    assert _read(blob) == plaintext[-50:]


def test_a_read_only_keyring_writes_in_the_clear_and_still_reads(
    tmp_path, keys, keyring
):
    _, storage = _local(tmp_path, keyring)
    storage.write("then.bin", b"encrypted while it was on")
    reader = Keyring(keys, None)
    inner, after = _local(tmp_path, reader)
    after.write("now.bin", b"written after it was unset")
    assert (
        inner.resolve_readable("now.bin").read_bytes() == b"written after it was unset"
    )
    assert _read(after.open_readable("then.bin")) == b"encrypted while it was on"


def test_a_keyring_without_a_root_makes_no_key(keys):
    assert Keyring(keys, None).key_for(GUILD, create=True) is None
    assert keys.rows == {}


def test_a_local_key_wrapped_for_one_community_does_not_unwrap_for_another(keys):
    Keyring(keys, LocalRoot()).key_for(GUILD, create=True)
    moved = KeyRow(**{**keys.rows[GUILD].__dict__, "guild_id": GUILD + 1})
    keys.rows[GUILD + 1] = moved
    with pytest.raises(storage_keys.StorageKeyError):
        Keyring(keys, LocalRoot()).key_for(GUILD + 1, create=False)


class _FakeKms:
    """Cloud KMS's encrypt and decrypt, keeping the plaintext and the
    associated data each ciphertext was made with."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.sealed: dict[str, tuple[str, str]] = {}

    def post(self, url: str, json: dict[str, str], timeout: float) -> Any:
        self.calls.append((url, json))
        verb = url.rsplit(":", 1)[1]

        class Answer:
            status_code = 200

            def __init__(self, body: dict[str, str]) -> None:
                self._body = body

            def json(self) -> dict[str, str]:
                return self._body

        if verb == "encrypt":
            token = base64.b64encode(os.urandom(12)).decode()
            self.sealed[token] = (
                json["plaintext"],
                json["additionalAuthenticatedData"],
            )
            return Answer({"ciphertext": token})
        plain, aad = self.sealed[json["ciphertext"]]
        if aad != json["additionalAuthenticatedData"]:
            Answer.status_code = 400
            return Answer({})
        return Answer({"plaintext": plain})


def test_a_kms_root_wraps_with_the_community_bound(keys, monkeypatch):
    kms = _FakeKms()
    monkeypatch.setattr(KmsRoot, "_authorized", lambda self: kms)
    name = "projects/p/locations/l/keyRings/r/cryptoKeys/storage-prod"
    ring = Keyring(keys, KmsRoot(name))
    found = ring.key_for(GUILD, create=True)
    assert found is not None

    row = keys.rows[GUILD]
    assert row.local_sealed is None and row.kms_key == name
    url, body = kms.calls[0]
    assert url.endswith(f"{name}:encrypt")
    assert (
        base64.b64decode(body["additionalAuthenticatedData"])
        == b"initiative-storage-key:guild:7"
    )
    # A fresh process unwraps it through KMS, whatever its own setting.
    assert Keyring(keys, None).key_for(GUILD, create=False) == found


def test_foss_gets_the_backend_itself(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "STORAGE_ENCRYPTION", "")
    storage_keys.use_keyring(None)
    assert isinstance(get_guild_storage(GUILD), LocalFilesystemStorage)


def test_an_encrypting_deployment_gets_the_wrapper(tmp_path, monkeypatch, keyring):
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))
    storage_keys.use_keyring(keyring)
    storage = get_guild_storage(GUILD)
    assert isinstance(storage, EncryptedStorage)
    storage.write("w.bin", b"through the resolver")
    assert _read(storage.open_readable("w.bin")) == b"through the resolver"
    assert storage_module.EncryptedStorage is EncryptedStorage


def test_a_part_retried_after_its_write_landed_is_sealed_afresh(
    tmp_path: Path, keyring: Keyring
) -> None:
    """The record of a part can fail after the part was written; the retry
    starts from the same state, possibly with other bytes. It must not seal
    them under the nonces the first attempt used."""
    inner, storage = _local(tmp_path, keyring)
    plaintext = os.urandom(2 * CHUNK)
    state = storage.start_parts("resumable-r", part_bytes=CHUNK, length=len(plaintext))
    storage.add_part("resumable-r", state, b"x" * CHUNK)
    first = inner.resolve_readable("resumable-r").read_bytes()
    state = storage.add_part("resumable-r", state, plaintext[:CHUNK])
    retried = inner.resolve_readable("resumable-r").read_bytes()
    span = slice(
        storage_crypto.HEADER_SIZE,
        storage_crypto.HEADER_SIZE + storage_crypto.NONCE_LEN,
    )
    assert first[span] != retried[span]
    state = storage.add_part("resumable-r", state, plaintext[CHUNK:])
    storage.finish_parts("resumable-r", state)
    assert _read(storage.open_readable("resumable-r")) == plaintext


def test_an_encrypting_store_refuses_a_file_of_unknown_length(
    tmp_path: Path, keyring: Keyring
) -> None:
    _, storage = _local(tmp_path, keyring)
    with pytest.raises(ValueError):
        storage.start_parts("resumable-n", part_bytes=CHUNK)


def test_storing_in_the_clear_with_keys_left_reopens_the_community(
    tmp_path: Path, keys: MemoryKeyStore, keyring: Keyring
) -> None:
    _, storage = _local(tmp_path, keyring)
    storage.write("then.bin", b"while it was on")
    assert keys.reopened == []
    _, after = _local(tmp_path, Keyring(keys, None))
    after.write("now.bin", b"after it was unset")
    after.start_parts("resumable-c", part_bytes=8, length=8)
    after.write(f"{EVIDENCE_KEY_PREFIX}e", b"sealed anyway")
    assert keys.reopened == [GUILD, GUILD]
