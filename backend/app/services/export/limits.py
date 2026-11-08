"""The export engine's bounds."""

#: Inline-vs-job auto-select: at or under this many rows the PDF renders
#: in-request; above it the request becomes a persisted export job.
EXPORT_INLINE_MAX_ROWS = 200
#: Hard ceiling on rows in one export snapshot (the list-endpoint pagination
#: caps do not apply to exports).
EXPORT_MAX_ROWS = 10_000
#: Per-user cap on jobs that are queued or running at once.
EXPORT_MAX_ACTIVE_JOBS_PER_USER = 5
#: How many export jobs one process renders at once. A community renders one
#: at a time whatever this says.
EXPORT_RENDER_SLOTS = 2

#: Aggregate (initiative/guild) exports: their own row ceiling — a guild dump
#: legitimately exceeds EXPORT_MAX_ROWS — and a byte cap on included uploads.
#:
#: The archive assembles on disk, one rendered artifact at a time
#: (``engine._stream_zip_to_storage``), so peak memory does not scale with how
#: much a community has. The byte cap is about how long a job may run and how
#: much scratch disk it may use, not about what fits in RAM.
#:
#: The row ceiling bounds the enumeration the adapter holds while it builds.
EXPORT_MAX_BACKUP_ROWS = 500_000
EXPORT_MAX_BACKUP_UPLOAD_BYTES = 10_737_418_240  # 10 GiB

#: Lifetime of a signed download URL. Short: it only has to outlive the
#: redirect and the start of the transfer.
EXPORT_DOWNLOAD_URL_TTL_SECONDS = 300
#: Artifact retention: expires_at = render time + this; the GC pass then
#: deletes the artifact and marks the job expired.
EXPORT_ARTIFACT_TTL_HOURS = 168  # 7 days

#: How many times an abandoned render is started over before its job fails.
EXPORT_MAX_RESTARTS = 2
