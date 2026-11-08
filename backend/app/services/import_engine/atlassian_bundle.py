"""The one zip an Atlassian fetch writes, whichever products it read.

Jira projects become project envelopes, their sprints calendar envelopes,
their images assets; Confluence spaces become wiki envelopes. All of it goes
into one backup-shaped bundle naming the one initiative the person picked, so
the apply is a single restore — and a link between an issue and a page read in
the same fetch has both of its ends in the same job to be joined.

The zip is written to a temporary file as the fetch goes: each attachment is
added the moment it has downloaded, and the envelopes and manifest once every
product has been read. Only the envelopes are held in memory, because the
passes that join issues, sprints and pages need all of them at once.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from app.core.tools import Tool, tool_envelope_type
from app.services.import_engine.common import handle_key
from app.services.import_engine.confluence_attachments import PageFile
from app.services.import_engine.jira_attachments import StoredImage

_MANIFEST_NAME = "manifest.json"

#: Types that are already compressed, stored as they are rather than deflated
#: again for nothing.
_COMPRESSED_TYPES = frozenset(
    {
        "application/pdf",
        "application/zip",
        "application/gzip",
        "application/x-7z-compressed",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
)


def _compression(content_type: str) -> int:
    kind = content_type.split(";", 1)[0].strip().lower()
    if kind in _COMPRESSED_TYPES or kind.startswith(("image/", "video/", "audio/")):
        return zipfile.ZIP_STORED
    return zipfile.ZIP_DEFLATED


def _safe(name: str, fallback: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in "-_") or fallback


def merge_people(
    jira: list[dict[str, Any]], confluence: Counter[str]
) -> list[dict[str, Any]]:
    """Everyone either product names, once each.

    The same person is usually in both — they wrote the pages and work the
    issues — and they are asked about once: keyed the way a handle is
    matched, Jira's spelling first, ordered by how much hangs on them.
    """
    seen: dict[str, dict[str, Any]] = {}
    weight: Counter[str] = Counter()
    for person in jira:
        key = handle_key(str(person["handle"]))
        seen.setdefault(key, dict(person))
        weight[key] += 1 + int(person.get("comment_count") or 0)
    for name, count in confluence.items():
        key = handle_key(name)
        seen.setdefault(key, {"handle": name, "name": name, "comment_count": 0})
        weight[key] += count
    return sorted(
        seen.values(),
        key=lambda person: (-weight[handle_key(person["handle"])], person["handle"]),
    )


class BundleWriter:
    """The zip the applier reads, written to a temporary file as it is read.

    Used as a context manager: the file is removed on the way out, once the
    caller has staged it. :meth:`put_asset` is the :data:`AssetSink` the
    downloaders are given; :meth:`finish` writes the envelopes and the
    manifest and closes the zip, after which :attr:`path` is the bundle.
    """

    def __init__(self) -> None:
        with tempfile.NamedTemporaryFile(
            prefix="import-bundle-", suffix=".zip", delete=False
        ) as handle:
            self.path = Path(handle.name)
        self._archive: zipfile.ZipFile | None = zipfile.ZipFile(
            self.path, "w", zipfile.ZIP_DEFLATED
        )
        self._assets: set[str] = set()
        self._lock = asyncio.Lock()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.discard()

    def discard(self) -> None:
        """Close the zip if it is still open and remove the file."""
        if self._archive is not None:
            self._archive.close()
            self._archive = None
        self.path.unlink(missing_ok=True)

    def _open(self) -> zipfile.ZipFile:
        if self._archive is None:
            raise RuntimeError("bundle already finished")
        return self._archive

    async def put_asset(self, stored: StoredImage, source: Path) -> None:
        """Add one downloaded file under ``assets/``, from the file on disk it
        was downloaded to, a chunk at a time. A key already written is not
        written twice."""
        path = f"assets/{stored.storage_key}"
        if path in self._assets:
            return
        self._assets.add(path)
        async with self._lock:
            await asyncio.to_thread(
                self._open().write,
                source,
                path,
                compress_type=_compression(stored.content_type),
            )

    def finish(
        self,
        *,
        projects: Sequence[tuple[str, dict[str, Any]]] = (),
        calendars: Sequence[dict[str, Any]] = (),
        images: Sequence[StoredImage] = (),
        wikis: Sequence[tuple[str, dict[str, Any]]] = (),
        wiki_files: Mapping[str, Sequence[PageFile]] = {},
        task_files: Sequence[StoredImage] = (),
        people: list[dict[str, Any]],
        guild_id: int,
        guild_name: str,
        target_initiative_id: int,
        app_version: str,
        site_url: str,
    ) -> Path:
        """Write the envelopes and the manifest, close the zip, and return
        where it is. Blocking; run it in a thread.

        The manifest names **one** initiative and gives it
        ``target_initiative_id`` — the one the person picked — so the applier
        files everything into it rather than creating one named after a site.

        ``wiki_files`` are the uploaded files each space's pages had attached,
        by the space's key: each is an entry of its own, filed in its wiki
        under the page it was attached to, and named by its asset's path — the
        ref a page's mention of it carries.

        ``task_files`` are the files Jira issues had attached: each an entry
        of its own, which the task it came from is attached to by that same
        ref.

        Only the files listed here are in the manifest. Anything else put in
        ``assets/`` — a picture no page ended up showing — stays in the zip
        unlisted, and the restore, which reads the manifest, passes over it.
        """
        archive = self._open()
        entries: list[dict[str, Any]] = []

        def add(
            tool: str, envelope_type: str, path: str, title: str, envelope: dict
        ) -> None:
            archive.writestr(path, json.dumps(envelope))
            entries.append(
                {
                    "path": path,
                    "tool": tool,
                    "type": envelope_type,
                    "schema_version": 1,
                    "entity_id": len(entries) + 1,
                    "title": title,
                    "initiative_id": 1,
                    "tags": [],
                    "properties": [],
                    "asset": None,
                }
            )

        for index, (key, envelope) in enumerate(projects, start=1):
            add(
                Tool.project.value,
                tool_envelope_type(Tool.project),
                f"initiatives/1-imported/projects/{index}-{_safe(key, 'project')}"
                ".initiative-project.json",
                envelope["project"]["name"],
                envelope,
            )
        for index, calendar in enumerate(calendars, start=1):
            add(
                Tool.calendar.value,
                tool_envelope_type(Tool.calendar),
                f"initiatives/1-imported/calendars/{index}-{_safe(calendar['name'], 'sprints')}"
                ".initiative-calendar.json",
                calendar["name"],
                calendar,
            )
        files: list[StoredImage] = []
        for index, (key, envelope) in enumerate(wikis, start=1):
            wiki_path = (
                f"initiatives/1-imported/wikis/{index}-{_safe(key, 'space')}"
                ".initiative-wiki.json"
            )
            add(
                Tool.wiki.value,
                tool_envelope_type(Tool.wiki),
                wiki_path,
                envelope["name"],
                envelope,
            )
            for page_file in wiki_files.get(key, ()):
                file = page_file.stored
                files.append(file)
                entries.append(
                    {
                        "path": f"assets/{file.storage_key}",
                        "tool": Tool.file.value,
                        "type": "file",
                        "schema_version": None,
                        "entity_id": len(entries) + 1,
                        "title": file.filename,
                        "initiative_id": 1,
                        "tags": [],
                        "properties": [],
                        "asset": f"assets/{file.storage_key}",
                        "attach_to": {
                            "kind": "wiki",
                            "ref": wiki_path,
                            "page": page_file.page_slug,
                        },
                    }
                )

        for file in task_files:
            files.append(file)
            entries.append(
                {
                    "path": f"assets/{file.storage_key}",
                    "tool": Tool.file.value,
                    "type": "file",
                    "schema_version": None,
                    "entity_id": len(entries) + 1,
                    "title": file.filename,
                    "initiative_id": 1,
                    "tags": [],
                    "properties": [],
                    "asset": f"assets/{file.storage_key}",
                }
            )

        assets = []
        listed: set[str] = set()
        for image in (*images, *files):
            path = f"assets/{image.storage_key}"
            if path not in self._assets:
                raise RuntimeError(f"asset listed but never written: {path}")
            if path in listed:
                continue
            listed.add(path)
            assets.append(
                {
                    "path": path,
                    "storage_key": image.storage_key,
                    "original_filename": image.filename,
                    "content_type": image.content_type,
                    "size_bytes": image.size_bytes,
                }
            )

        tools = {
            tool.value: "included"
            for tool, present in (
                (Tool.project, projects),
                (Tool.calendar, calendars),
                (Tool.wiki, wikis),
                (Tool.file, files),
            )
            if present
        }
        manifest = {
            "type": "initiative-backup",
            "schema_version": 1,
            "app_version": app_version,
            "exported_at": datetime.now(UTC).isoformat(),
            "source_instance_url": site_url,
            "guild": {"id": guild_id, "name": guild_name},
            "include_uploads": bool(assets),
            "initiatives": [
                {
                    "id": 1,
                    "name": "Imported from Atlassian",
                    "tools": tools,
                    # Apply into the initiative the person chose rather than a
                    # new one named after the site: they already said where
                    # it goes.
                    "target_initiative_id": target_initiative_id,
                }
            ],
            "entries": entries,
            "assets": assets,
            "skipped": [],
            "people": people,
        }
        archive.writestr(_MANIFEST_NAME, json.dumps(manifest))
        archive.close()
        self._archive = None
        return self.path
