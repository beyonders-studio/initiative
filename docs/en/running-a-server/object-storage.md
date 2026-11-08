---
icon: lucide/hard-drive
---

# File & object storage

Every file people bring into Initiative goes through one storage backend: attachments, uploads in Files and their versions, pictures pasted into pages, exports and imports. Local disk suits most servers. An S3-compatible bucket is one settings tab away, and so are two extras: encrypting files in Initiative before they're stored, and scanning them before they're kept.

## Choosing where files live

The [owner](platform-roles.md) chooses under **Settings → Platform → Storage**, in **Storage backend**:

| Choice | Where files go |
|---|---|
| **Local filesystem** (the default) | The server's disk, under `UPLOADS_DIR`: `/app/uploads` in the image, which the example compose file mounts from `./uploads` |
| **S3-compatible** | A bucket on any store that speaks the S3 API, such as a self-hosted Garage or MinIO, Cloudflare R2, or a cloud provider's object storage |

Initiative brings no object store of its own; you point it at yours. A saved change takes effect at once on the copy that saved it and within 30 seconds on any others. The `STORAGE_BACKEND` and `S3_*` variables fill this tab in on a server's first start only (see [Configuration](configuration.md#read-on-the-first-start-only)).

## How files are laid out

| Backend | Where a community's files are |
|---|---|
| Local | `UPLOADS_DIR/guild_<id>/<file>` |
| S3 | Keys under the prefix `guild_<id>/` |

`guild_<id>` is the community's id. Either way, a file's address is `/uploads/<community id>/<file>`, and every download is checked against the person asking, with the same membership and access checks as everything else, before Initiative streams it back. Where a file physically sits never changes who may read it. See [How your data is kept separate](../security/how-your-data-is-kept-separate.md).

## Connecting an S3-compatible store

From your store you need an S3 API endpoint, the region it signs with, a bucket that already exists, and an access key that can read and write it.

| Field | What it takes |
|---|---|
| **Bucket** | The bucket's name. Initiative reads and writes objects in it and never creates one. |
| **Region** | The region your store signs requests with, such as `garage` for a default Garage. Starts as `us-east-1`. |
| **Endpoint URL** | The store's S3 API address, such as `http://garage:3900` |
| **Access key ID** | The key's id. Blank uses whatever credentials the server's environment provides. |
| **Secret access key** | The key's secret, stored encrypted and never shown again. Leave it blank when editing to keep the saved one. |
| **Path-style addressing** | On for Garage and most self-hosted stores, which address objects as `https://host/bucket/key`. Off, the default, for stores that use `https://bucket.host/key`. |
| **Serve missing objects from local** | While moving to S3, read a file that isn't in the bucket yet from local disk |

**Test connection** checks what's in the form, saved or not, so you can try a setting before committing to it.

For encryption at rest, turn on your store's default encryption for the bucket and every file Initiative writes picks it up. To have Initiative encrypt files itself, so the store only ever holds ciphertext, see [Encrypting stored files](#encrypting-stored-files).

## Moving existing files to S3

Switching the backend changes where new files go. Files already on disk have to be copied across, and this way nothing goes missing while they are:

1. Fill in the S3 fields, select **Test connection**, and fix anything it reports.
2. Set **Storage backend** to **S3-compatible**, turn on **Serve missing objects from local**, and select **Save**. From then on, new files go to the bucket, and a file that isn't there yet is read from disk.
3. Under **Backfill local files to S3**, select **Start backfill**. It copies every file under `UPLOADS_DIR` into the bucket under the same name and recorded type, skips any that are already there, and shows **Copied**, **Skipped** and **Failed** as it goes.
4. When it says **Complete** with nothing failed, turn off **Serve missing objects from local** and select **Save**.
5. Once files open from the bucket, retire the old uploads folder.

A run that ends **Failed** can be started again, and carries on from where it got to. One run goes at a time across every copy of Initiative. Give the key `s3:ListBucket` on the bucket too; without it, many stores can't say a file is missing, so a second run copies everything again rather than skipping what's there.

??? techspec "The same copy from a shell"
    `python -m app.db.backfill_uploads_to_s3` does what **Start backfill** does, and `--dry-run` reports what it would copy without writing anything. It reads the bucket from the environment rather than the saved settings, so give it `STORAGE_BACKEND=s3` and the `S3_*` values:

    ```bash
    docker compose exec -T \
      -e STORAGE_BACKEND=s3 -e S3_BUCKET=initiative \
      -e S3_ENDPOINT_URL=http://garage:3900 -e S3_REGION=garage \
      -e S3_ACCESS_KEY_ID=GK... -e S3_SECRET_ACCESS_KEY=... \
      -e S3_USE_PATH_STYLE=true \
      initiative python -m app.db.backfill_uploads_to_s3 --dry-run
    ```

    It ends with `copied=`, `skipped=`, `failed=` and `hash_mismatches=` counts, and exits with status 1 when anything failed.

## Encrypting stored files

Off by default, and most servers leave it off. Turn it on when the people who can reach your disk or bucket shouldn't be able to read what communities store, for a compliance requirement, say.

With `STORAGE_ENCRYPTION` set, Initiative encrypts every file a community stores before it reaches the backend: uploads, file versions, exports, staged imports, and a large file while its pieces are still arriving. Each file gets its own key and is sealed with AES-256-GCM in 64 KB chunks. That key is wrapped by a key belonging to the community, and the community's key is wrapped by a root you choose:

| `STORAGE_ENCRYPTION` | The root |
|---|---|
| Unset (the default) | None. Files are stored as they arrive. |
| `local` | Your `SECRET_KEY`. Nothing else to set up. |
| `gcp_kms` | The Google Cloud KMS key named in `STORAGE_ENCRYPTION_KMS_KEY`, as `projects/<p>/locations/<l>/keyRings/<r>/cryptoKeys/<k>`. Initiative calls KMS as its own Google identity, whose service account needs `roles/cloudkms.cryptoKeyEncrypterDecrypter` on that key. The start stops if the key isn't named. |

It works with both backends, and it's a deployment setting on purpose: nothing in the app turns it off. Restart after changing it.

Downloads, previews and video seeking work as usual. Initiative decrypts as it streams, and a byte range reads only the chunks it covers.

**Files you already have** keep reading as they are. A background pass re-writes each one encrypted, in place and under the same name, one community at a time, until everything is. It first runs 10 minutes after a process starts and then every 6 hours, one process at a time. On an S3 bucket with versioning, the old unencrypted copy stays as the object's previous version until your bucket's lifecycle rules remove it.

**When a community is destroyed**, at the end of its [retention window](configuration.md#how-long-deleted-things-are-kept), its key is destroyed first. Every file it stored becomes unreadable at once, wherever a copy sits, including old versions in a bucket and any copy somebody made. Another process may hold the key in memory for up to 5 minutes.

Things to know:

- **With `local`, `SECRET_KEY` is what opens your files.** Lose it and they can't be read, so back it up wherever you keep your other secrets. [Changing it](configuration.md#changing-the-secret-key) re-wraps the community keys and never touches the files.
- **With `gcp_kms`, opening a file needs KMS.** A community's key stays in memory for 5 minutes after use, so a brief outage goes unnoticed. A longer one stops files opening in communities whose keys have expired from memory.
- **A key opens with the root that wrapped it**, whatever `STORAGE_ENCRYPTION` says later, so switching between `local` and `gcp_kms` strands nothing as long as the old root is around.
- **Direct download links are off for encrypted files.** `EXPORT_PRESIGNED_DOWNLOADS` does nothing for them, because the bucket holds ciphertext, and exports stream through Initiative.
- **Unsetting it** stores new files as they arrive. Files stored encrypted keep opening as long as their keys and the root are there.

## Scanning uploads

Off by default. Turn it on when files should be checked for malware before anything keeps them.

With `UPLOAD_SCANNER_URL` and `UPLOAD_SCANNER_TOKEN` set, Initiative sends every file a person or an import brings in to the scanner before storing it: uploads, new versions, pasted pictures, evidence, and a large file once all its pieces have arrived. Setting the URL without the token stops the start.

The scanner is a separate service that Initiative calls over HTTP. Any service that answers this way works:

| Part of the exchange | What it is |
|---|---|
| Request | `POST <UPLOAD_SCANNER_URL>/v1/scan`, with the file as the body, `Content-Type: application/octet-stream`, its `Content-Length`, and `Authorization: Bearer <UPLOAD_SCANNER_TOKEN>` |
| `200` with `{"verdict": "clean"}` | The file is stored. |
| `200` with `{"verdict": "refused", "engine": "…", "reason": "…"}` | The file is refused and nothing of it is kept. The log records the engine and the reason. |
| `413` | The file is larger than the scanner takes, and is refused. |
| Anything else, or no answer | Uploads are paused. |
| Time allowed | 5 seconds to connect, and 900 seconds each to send the file and to read the answer |

A refused file shows the person **This file was refused by the malware scan.**

Scanning fails closed. While the scanner can't answer, every upload is refused with **Uploads are paused while files can't be scanned. Try again in a few minutes.**, so a server that asked for scanning never stores a file it didn't scan.

## Per-community storage limits

Separately from where files are stored, operators and owners can cap how much each community stores, under **Operator dashboard › Communities**, in the community's **Limits**: **Storage limit**, in gigabytes, blank for no limit. Lowering a limit below what a community already holds blocks new uploads and never deletes a file.
