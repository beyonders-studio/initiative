---
icon: lucide/hard-drive
---

# File & object storage

Uploaded files — image attachments, uploads in Files, and their versions — go through a pluggable storage backend. By default everything lives on local disk, which is right for most deployments. Prefer S3-compatible object storage? That's a configuration change and nothing else.

## Choosing a backend

The `STORAGE_BACKEND` environment variable selects where uploads live:

| `STORAGE_BACKEND` | Where uploads go |
|---|---|
| `local` *(default)* | The filesystem, under `UPLOADS_DIR`. |
| `s3` | Any S3-compatible object store you point it at. |

Nothing object-store-related runs unless you opt in with `STORAGE_BACKEND=s3`. Initiative never runs or bundles an object store of its own — you bring your own (for example, a [Garage](https://garagehq.deuxfleurs.fr/) node, MinIO, or a cloud provider's S3-compatible storage).

## How files are organized

Both backends namespace files **per community**, mirroring the database's per-community isolation:

- **Local:** `UPLOADS_DIR/guild_<id>/<file>`.
- **Object storage:** objects under a `guild_<id>/` key prefix.

!!! note "Why the paths say `guild`"
    Communities used to be called guilds. The user-facing name changed; the storage paths and internal identifiers didn't, because renaming them would move every existing file for no benefit. `guild_<id>` is a community — same thing, older name.

Either way the download URL is the same (`/uploads/{community_id}/{filename}`), and **every download is authorized on the request** — files stream back through the app only after the same community-membership and access checks as everything else. Where a file physically sits never affects who may read it. See [How your data is kept separate](../security/how-your-data-is-kept-separate.md).

## Connecting an S3-compatible store

You'll need, from your store: an **S3 API endpoint**, the **region** it was configured with, an existing **bucket**, and an **access key** (id + secret) with read/write on that bucket. Then set:

```bash
STORAGE_BACKEND=s3
S3_BUCKET=initiative                  # an existing bucket on your store
S3_ENDPOINT_URL=http://garage:3900    # your store's S3 API endpoint
S3_REGION=garage                      # must match the store's configured region
S3_ACCESS_KEY_ID=GK...
S3_SECRET_ACCESS_KEY=...
S3_USE_PATH_STYLE=true                # true for Garage and most self-hosted stores
```

Notes:

- **`S3_USE_PATH_STYLE`** — `true` for Garage and most self-hosted stores (path-style URLs like `https://host/bucket/key`). Set `false` only for a store that uses virtual-host-style addressing.
- **`S3_REGION`** must match the region your store enforces in its request signature.
- **Credentials** — set the access key id/secret, or leave them unset to use the ambient credential chain where your store supports it.
- The **bucket must already exist**; Initiative reads and writes objects but doesn't create the bucket.
- **Encryption at rest** belongs to the bucket by default. Turn on your store's default encryption there and every file Initiative writes picks it up. If you want the files encrypted by Initiative itself, so the store only ever holds ciphertext, see [Encrypting stored files](#encrypting-stored-files).

## Migrating an existing deployment from local to S3

Switching the backend only changes where **new** uploads go — files already on local disk must be copied across first. The process is designed to be zero-downtime.

**1. Backfill while still on `local`.** With the `S3_*` settings pointed at your store but `STORAGE_BACKEND` still `local`, copy existing files into the bucket:

```bash
python -m app.db.backfill_uploads_to_s3 --dry-run   # preview
python -m app.db.backfill_uploads_to_s3             # copy for real
```

It uploads each file with its recorded content type and verifies it, and it's **idempotent** — safe to re-run until it reports `failed=0`.

**2. Cut over with a fallback window.** Set:

```bash
STORAGE_BACKEND=s3
S3_LOCAL_FALLBACK=true
```

With the fallback on, a read that misses in S3 falls back to local disk, so nothing 404s during the transition. New uploads now go to S3.

**3. Finish.** Once everything serves from S3 and a final backfill reports `failed=0`, set `S3_LOCAL_FALLBACK=false` and retire the local uploads volume.

## Encrypting stored files

Off by default, and most deployments leave it off. Turn it on when the people who can reach your disk or bucket should not be able to read what communities store, for example to meet a compliance requirement.

**What it does.** With `STORAGE_ENCRYPTION` set, Initiative encrypts every file a community stores before it reaches the backend: uploads, file versions, exports, staged imports, and a large file while it is still arriving in pieces. Each file gets its own key. That key is wrapped by a key belonging to the community, and the community's key is wrapped by a root you choose:

| `STORAGE_ENCRYPTION` | The root |
|---|---|
| *(unset, the default)* | No encryption by Initiative. Files are stored as they arrive. |
| `local` | Your `SECRET_KEY`. Nothing else to set up. |
| `gcp_kms` | A Google Cloud KMS key, named in `STORAGE_ENCRYPTION_KMS_KEY` (`projects/<p>/locations/<l>/keyRings/<r>/cryptoKeys/<k>`). Initiative calls KMS as its own Google identity, so its service account needs `roles/cloudkms.cryptoKeyEncrypterDecrypter` on that key. |

Downloads, previews and video seeking work as before: Initiative decrypts as it streams, and a byte range reads only the part of the file it needs.

**Files you already have.** Turning it on doesn't make old files unreadable. They keep reading as they are, and a background pass re-writes each one encrypted, a community at a time, until everything is. On an S3 store the old plaintext stays as the object's previous version until your bucket's lifecycle rules remove it.

**Deleting a community.** When a community is deleted, its key is destroyed first. Every file it stored becomes unreadable at once, wherever a copy of it sits, including old versions in a bucket and any copy someone made.

**Things to know:**

- **With `local`, your `SECRET_KEY` now protects your files.** Lose it and the files can't be read. Back it up wherever you back up your other secrets. Rotating it the documented way (`PREVIOUS_SECRET_KEY`) re-wraps the community keys and never touches the files.
- **With `gcp_kms`, opening a file needs KMS.** Keys are cached in memory for a few minutes, so a brief KMS outage goes unnoticed. A long one stops files opening in communities whose keys aren't cached.
- **Direct download links are off for encrypted files.** `EXPORT_PRESIGNED_DOWNLOADS` has no effect, because the store holds ciphertext. Exports stream through Initiative.
- **Turning it off again** stops new files from being encrypted. Files stored encrypted still read, as long as their keys and `SECRET_KEY` (or the KMS key) are still there.

## Per-community storage limits

Separately from *where* files are stored, the [owner](platform-roles.md) can cap **how much** each community may store, from **Settings → Platform → Communities**. Lowering a limit below a community's current usage blocks *new* uploads but never deletes existing files.

## Related

- [Configuration](configuration.md) · [Backups & updates](backups-and-updates.md)
- [How your data is kept separate](../security/how-your-data-is-kept-separate.md) — why downloads stay gated.
