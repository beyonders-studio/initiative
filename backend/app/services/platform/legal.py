"""A deployment's own terms, and the record that an account accepted them.

The documents are not in this repository. A deployment that has terms of its
own names an external portal in ``BILLING_URL`` and they are served from
there; unset — the default — and none of this runs: there is nothing to
accept, nothing is recorded, and every route answers 404.

They are read through this module rather than by the browser for three
reasons: the native build's origin is not an ``https://`` one, and a policy
has to be readable from the signup form there too; the server needs the index
anyway, to record *which* revision was accepted; and signing up must not
depend on a browser reaching a second origin.

Which documents an account must accept is the portal's to say: each index
entry carries ``required``. A deployment may require none at all (an
enterprise whose terms sit in its own contract, or in an employment one), and
then signup asks for nothing and records nothing. A document may also live
elsewhere (``url``, the customer's own contract): it is linked, never fetched
through here, and carries no digest.

Nothing here can fail a registration, and nothing here invents a required
document. A portal that cannot be reached, and was never read, requires
nothing for now: the signup records no acceptance, and the account is asked
once the index can be read again.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx2
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.platform.legal_acceptance import LegalAcceptance
from app.models.platform.user import User

logger = logging.getLogger(__name__)

INDEX_PATH = "/api/v1/legal"

#: Short: every one of these calls sits in front of somebody waiting to read
#: a policy or finish signing up.
_TIMEOUT = httpx2.Timeout(4.0, connect=2.0)

#: How long an index is trusted before it is asked for again. Revisions are
#: rare; the cost of being a few minutes behind is a version string.
_INDEX_TTL_SECONDS = 300

#: How long a portal never read is left alone after a failed read, so every
#: account read in an outage doesn't wait on it.
_FAILURE_BACKOFF_SECONDS = 30


@dataclass(frozen=True)
class LegalDocument:
    """One document as the portal's index describes it — never its text."""

    slug: str
    title: str
    version: str | None
    effective_date: str | None
    sha256: str | None
    #: Whether an account must accept it to exist here.
    required: bool = False
    #: Where it lives when the portal doesn't serve it: linked, never fetched.
    url: str | None = None


@dataclass(frozen=True)
class FetchedDocument:
    """One document's bytes, as the portal served them."""

    content: bytes
    media_type: str
    etag: str | None


class LegalPortalUnavailable(Exception):
    """The portal could not be reached, or answered with something that is not
    a legal index."""


_index_lock = asyncio.Lock()
#: (fetched_at, documents). Kept past its TTL so an outage degrades to a stale
#: answer rather than to none at all.
_index_cache: tuple[float, tuple[LegalDocument, ...]] | None = None
#: When a read last failed with nothing cached to answer from.
_index_failed_at: float | None = None


def legal_documents_enabled() -> bool:
    """Whether this deployment has terms to accept.

    True exactly when it names an external portal to serve them from.
    """
    return bool(settings.BILLING_URL)


def _portal_url(path: str) -> str:
    return settings.BILLING_URL.rstrip("/") + path


def _parse_index(payload: object) -> tuple[LegalDocument, ...]:
    if not isinstance(payload, dict):
        raise LegalPortalUnavailable("legal index is not an object")
    raw = payload.get("documents")
    if not isinstance(raw, list):
        raise LegalPortalUnavailable("legal index has no documents list")
    documents: list[LegalDocument] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug")
        title = entry.get("title")
        if not isinstance(slug, str) or not isinstance(title, str):
            continue
        url = entry.get("url")
        if url is not None and not (
            isinstance(url, str) and url.startswith("https://")
        ):
            # Linked from the signup form: only an https address will do.
            continue
        documents.append(
            LegalDocument(
                slug=slug,
                title=title,
                version=entry.get("version")
                if isinstance(entry.get("version"), str)
                else None,
                effective_date=entry.get("effective_date")
                if isinstance(entry.get("effective_date"), str)
                else None,
                sha256=entry.get("sha256")
                if isinstance(entry.get("sha256"), str)
                else None,
                required=entry.get("required") is True,
                url=url,
            )
        )
    return tuple(documents)


async def get_index(*, force: bool = False) -> tuple[LegalDocument, ...]:
    """The portal's legal index, cached for :data:`_INDEX_TTL_SECONDS`.

    Raises :class:`LegalPortalUnavailable` only when there is nothing cached
    to fall back on — a portal that goes down after one good read keeps
    answering from that read.
    """
    global _index_cache, _index_failed_at
    if not legal_documents_enabled():
        raise LegalPortalUnavailable("no billing portal is configured")

    cached = _index_cache
    if (
        not force
        and cached is not None
        and time.monotonic() - cached[0] < _INDEX_TTL_SECONDS
    ):
        return cached[1]

    async with _index_lock:
        # Another caller may have refreshed it while this one waited.
        cached = _index_cache
        if (
            not force
            and cached is not None
            and time.monotonic() - cached[0] < _INDEX_TTL_SECONDS
        ):
            return cached[1]
        failed = _index_failed_at
        if (
            not force
            and cached is None
            and failed is not None
            and time.monotonic() - failed < _FAILURE_BACKOFF_SECONDS
        ):
            raise LegalPortalUnavailable("the portal's index was unreadable just now")
        try:
            async with httpx2.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.get(
                    _portal_url(INDEX_PATH), headers={"Accept": "application/json"}
                )
                response.raise_for_status()
                documents = _parse_index(response.json())
        except Exception as exc:
            if cached is not None:
                logger.warning(
                    "legal: portal index unreadable (%s); serving the last one read",
                    exc,
                )
                return cached[1]
            logger.warning("legal: portal index unreadable (%s)", exc)
            _index_failed_at = time.monotonic()
            raise LegalPortalUnavailable(str(exc)) from exc
        _index_cache = (time.monotonic(), documents)
        _index_failed_at = None
        return documents


#: The characters a document's slug is written in.
_SLUG_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")
#: The types a document is served as; anything else the portal names is
#: served as plain text.
_DOCUMENT_TYPES = ("text/markdown", "text/plain")


async def get_document(
    slug: str, *, if_none_match: str | None = None
) -> FetchedDocument:
    """One document's bytes, straight from the portal.

    Not cached here: the portal serves it with a content ETag and no freshness
    lifetime, which the caller forwards, so the reader's own browser does the
    caching and a corrected policy still reaches them on their next look.
    """
    if not legal_documents_enabled():
        raise LegalPortalUnavailable("no billing portal is configured")
    if not slug or not set(slug) <= _SLUG_CHARACTERS:
        raise KeyError(slug)
    try:
        indexed = {document.slug: document for document in await get_index()}
    except LegalPortalUnavailable:
        indexed = {}
    if slug in indexed and indexed[slug].url is not None:
        # Hosted elsewhere: the reader follows its link, and the portal has
        # no text for it.
        raise KeyError(slug)
    headers = {"Accept": "text/markdown, text/plain"}
    if if_none_match:
        headers["If-None-Match"] = if_none_match
    try:
        async with httpx2.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                _portal_url(f"{INDEX_PATH}/{slug}"), headers=headers
            )
    except Exception as exc:
        raise LegalPortalUnavailable(str(exc)) from exc
    if response.status_code == 304:
        return FetchedDocument(
            content=b"", media_type="", etag=response.headers.get("etag")
        )
    if response.status_code == 404:
        raise KeyError(slug)
    if response.status_code >= 400:
        raise LegalPortalUnavailable(f"portal answered {response.status_code}")
    media_type = response.headers.get("content-type", "text/markdown; charset=utf-8")
    if not media_type.startswith(_DOCUMENT_TYPES):
        media_type = "text/plain; charset=utf-8"
    return FetchedDocument(
        content=response.content,
        media_type=media_type,
        etag=response.headers.get("etag"),
    )


async def required_documents() -> tuple[LegalDocument, ...]:
    """The documents an account must accept, as the portal's index says.

    None when the portal requires none, and none when it can't be read and was
    never read: a required document is never invented here.
    """
    try:
        return tuple(document for document in await get_index() if document.required)
    except LegalPortalUnavailable:
        return ()


async def record_acceptance(
    session: AsyncSession, *, user_id: int, shown: Collection[str] | None = None
) -> None:
    """Write this account's acceptance of every required document, if any;
    with ``shown``, only of the required ones it names (the documents a form
    showed the person, by slug), so nothing unseen is recorded as agreed.

    Staged, never committed — the caller owns the transaction. Callers that
    may run twice for one account should check :func:`acceptance_outstanding`
    first; a second call would append a second row rather than fail, because
    the log records events and re-consent is a real one.
    """
    if not legal_documents_enabled():
        return
    now = datetime.now(UTC)
    for document in await required_documents():
        if shown is not None and document.slug not in shown:
            continue
        session.add(
            LegalAcceptance(
                user_id=user_id,
                document=document.slug,
                version=document.version,
                document_sha256=document.sha256,
                accepted_at=now,
            )
        )


async def acceptance_outstanding(session: AsyncSession, *, user: User) -> bool:
    """Whether this account still owes an acceptance before it may carry on.

    Asked of every read of the caller's own account, so it short-circuits on
    the deployment switch for every self-hoster, and on a deployment that
    requires nothing; elsewhere it costs the cached index and one indexed
    count.

    The question is "has this account ever accepted each required document",
    not "…the current revision of each": publishing a new revision must not
    interrupt everybody who is already here. Re-consent on a revision change
    would be a deliberate change to this predicate.
    """
    if not legal_documents_enabled():
        return False
    required = [document.slug for document in await required_documents()]
    if not required:
        return False
    accepted = (
        await session.exec(
            select(func.count(func.distinct(LegalAcceptance.document))).where(
                LegalAcceptance.user_id == user.id,
                LegalAcceptance.document.in_(required),  # type: ignore[attr-defined]
            )
        )
    ).one()
    return accepted < len(required)


def reset_index_cache() -> None:
    """Forget the cached index. For tests."""
    global _index_cache, _index_failed_at
    _index_cache = None
    _index_failed_at = None
