"""The import engine's bounds (the counterpart of the export engine's)."""

#: Inline-vs-job auto-select: at or under this many rows the envelope applies
#: in-request; above it the payload is staged and a job queued.
IMPORT_INLINE_MAX_ROWS = 200
#: Hard ceiling on rows in one envelope import.
IMPORT_MAX_ROWS = 10_000
#: Per-user cap on jobs that are staged, queued, or running at once.
IMPORT_MAX_ACTIVE_JOBS_PER_USER = 5
#: Byte bound on a single envelope request body (rows bound the content, but a
#: single-field envelope must be bounded in bytes too). One JSON member of an
#: uploaded zip — an envelope or its manifest — is held to it as well, so an
#: envelope reads the same whether it arrives alone or zipped.
IMPORT_MAX_ENVELOPE_BYTES = 20_971_520  # 20 MiB
#: Staged payloads awaiting confirm/apply expire after this.
IMPORT_STAGED_TTL_HOURS = 24

#: The most a zip may weigh — a backup sent with one request, a wiki with its
#: files, a Confluence space's HTML export — plus the bounds every zip but a
#: backup is opened within, independent of the transfer cap: total declared
#: uncompressed size and member count.
IMPORT_MAX_BACKUP_UPLOAD_BYTES = 268_435_456  # 256 MiB
IMPORT_MAX_ZIP_UNCOMPRESSED_BYTES = 1_073_741_824  # 4x the upload cap
IMPORT_MAX_ZIP_MEMBERS = 20_000

#: The longest a fetch may spend reading a foreign site, from its first call
#: to its bundle being staged. Past it the job fails with
#: ``IMPORT_SOURCE_TOO_SLOW`` rather than holding its slot.
IMPORT_FETCH_DEADLINE_SECONDS = 4 * 60 * 60

#: How many imports one process runs at once, by kind. Fetches wait on a
#: foreign site; applies write to the database. One community has at most one
#: import fetching or running at a time, whatever the slots allow.
IMPORT_FETCH_SLOTS = 3
IMPORT_APPLY_SLOTS = 2

#: A backup, and a bundle a fetch writes itself — read from an Atlassian site,
#: or converted from a Confluence export — are opened within these rather than
#: the zip bounds above: a backup holds what an export puts in one, as much as
#: ``EXPORT_MAX_BACKUP_UPLOAD_BYTES`` of files beside its envelopes, and one
#: sent in pieces may weigh up to :data:`IMPORT_MAX_BUNDLE_BYTES`. The
#: community's storage quota narrows the attachment budget further
#: (``jira_attachments``).
#: Rows one fetch may bring: tasks, comments, pages, uploaded files.
IMPORT_FETCH_MAX_ROWS = 250_000
#: Declared uncompressed size of a bundle, files and envelopes together. Each
#: file is written to disk as it is read, so this is a disk bound.
IMPORT_MAX_BUNDLE_BYTES = 20 * 1024 * 1024 * 1024  # 20 GiB
#: Members of a bundle.
IMPORT_MAX_BUNDLE_MEMBERS = 250_000
#: One JSON member of a fetched bundle — an envelope or the manifest. A Jira
#: project's envelope has no byte bound of its own, only the row bound, and a
#: full row budget of envelopes runs to about a gigabyte
#: (``jira_attachments._BUNDLE_RESERVE_BYTES``), all of which one project may
#: hold. A wiki's is bounded tighter by ``IMPORT_FETCH_MAX_SPACE_BYTES``.
IMPORT_FETCH_MAX_ENVELOPE_BYTES = 1024 * 1024 * 1024  # 1 GiB
#: The converted content one Confluence space may carry; pages past it are
#: reported and left behind.
IMPORT_FETCH_MAX_SPACE_BYTES = 150 * 1024 * 1024  # 150 MiB

#: How deep a foreign document may nest before the converters stop
#: descending: an ADF body's nodes, a Confluence page's elements. Real content
#: sits well under it; past it, the walk costs a bounded amount of work rather
#: than a recursion error.
MAX_NESTING_DEPTH = 64
