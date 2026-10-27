"""A mention of somebody, carried across an export by handle.

Inside the app a mention names an account by id: ``@[Sam Bee](42)`` in
markdown (a task's description, a comment) and a Lexical ``mention`` node with
``mentionUserId`` in an editor state (a file, a post, a wiki page). An id
means nothing where an export is restored — on another instance, or in a
community where 42 is somebody else — so the export writes each mention as the
person's **handle** and lists it beside the text, and the restore links the
handles the people step placed, the way it already does for a Jira mention:

* markdown: ``@[Sam Bee](42)`` becomes ``@sam#0042`` and the handle joins the
  row's ``mention_handles``; ``project_import._link_mentions`` turns a placed
  one back into ``@[…](<id here>)``.
* editor state: the node keeps its name, loses its ``mentionUserId`` and
  carries ``mentionHandle`` instead; :func:`place_editor_mentions` gives a
  placed one the account and drops the handle. One nobody placed is a name
  with no account, which the editor already draws.

A mention of somebody whose account is gone (anonymized, or no longer
readable) crosses as the name it was written with where it has one, and
nothing else.

A rendered export is read away from the app, so :func:`mention_namer` writes
into it the name each mention reads as now.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.identity_boundary import (
    STORED_MENTION,
    MentionForm,
    without_mention_names,
)
from app.core.file_types import FileType
from app.core.user_display import handle_of
from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import UserStatus
from app.models.platform.user_profile_view import GuildMember, MemberProfile

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.services.import_engine.people import PeopleMap

#: The node types a person's mention is written as (``mention_parser``).
_MENTION_NODES = ("mention", "custom-mention")

#: The placeholder an exported mention node carries in place of its account.
MENTION_HANDLE = "mentionHandle"

#: A mention of somebody an export could not name: no account, and no name.
_NOBODY = "@[]()"


def markdown_mention_ids(text: str | None) -> set[int]:
    """The accounts a markdown body mentions."""
    return {int(match[1]) for match in STORED_MENTION.findall(text or "")}


def editor_mention_ids(content: Any) -> set[int]:
    """The accounts an editor state's mention nodes name."""
    found: set[int] = set()

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        user_id = node.get("mentionUserId")
        if node.get("type") in _MENTION_NODES and _is_id(user_id):
            found.add(user_id)
        for child in node.get("children") or []:
            walk(child)

    walk(content.get("root") if isinstance(content, dict) else None)
    return found


async def load_mention_handles(
    session: AsyncSession, user_ids: Iterable[int]
) -> dict[int, str]:
    """``user id → handle`` for the accounts named, as the routed session can
    read them. An erased account has a handle but no person behind it, so it is
    left out and its mentions cross as names."""
    wanted = set(user_ids)
    if not wanted:
        return {}
    rows = await session.exec(select(MemberProfile).where(MemberProfile.id.in_(wanted)))
    return {
        profile.id: handle_of(profile)
        for profile in rows.all()
        if profile.status != UserStatus.anonymized
    }


def detach_markdown_mentions(
    text: str | None, handles: Mapping[int, str]
) -> tuple[str | None, list[str]]:
    """``text`` with each mention written as ``@<handle>``, and the handles it
    now names, first-seen order."""
    if not text:
        return text, []
    named: list[str] = []

    def detach(match: re.Match[str]) -> str:
        handle = handles.get(int(match.group(2)))
        if handle is None:
            # One with no name stays a mention of nobody named, which reads as
            # a former member wherever it is shown.
            return f"@{match.group(1)}" if match.group(1) else _NOBODY
        if handle not in named:
            named.append(handle)
        return f"@{handle}"

    return STORED_MENTION.sub(detach, text), named


def detach_editor_mentions(
    content: Any, handles: Mapping[int, str]
) -> tuple[Any, list[str]]:
    """``content`` with each mention node naming a handle instead of an
    account, and the handles it now names. Returns new dicts wherever something
    changed and never edits ``content`` itself — it is usually a loaded row's
    column."""
    if not isinstance(content, dict) or not isinstance(content.get("root"), dict):
        return content, []
    named: list[str] = []

    def walk(node: Any) -> Any:
        if not isinstance(node, dict):
            return node
        if node.get("type") in _MENTION_NODES and _is_id(node.get("mentionUserId")):
            detached = {**node, "mentionUserId": None}
            handle = handles.get(node["mentionUserId"])
            if handle is not None:
                detached[MENTION_HANDLE] = handle
                if handle not in named:
                    named.append(handle)
            return detached
        children = node.get("children")
        if isinstance(children, list):
            return {**node, "children": [walk(child) for child in children]}
        return node

    return {**content, "root": walk(content["root"])}, named


def place_mention_node(node: dict[str, Any], account: int | None) -> dict[str, Any]:
    """An exported mention node, linked to ``account`` with no name if somebody
    here was placed on its handle, and a name with no account if not."""
    placed = {k: v for k, v in node.items() if k != MENTION_HANDLE}
    placed["mentionUserId"] = account
    return without_mention_names(placed, MentionForm.lexical)


def place_editor_mentions(
    content: Any, account_for: Callable[[str], int | None]
) -> Any:
    """``content`` with every exported mention node placed through
    ``account_for`` (a handle → the account it is here, or None)."""
    if not isinstance(content, dict) or not isinstance(content.get("root"), dict):
        return content

    def walk(node: Any) -> Any:
        if not isinstance(node, dict):
            return node
        handle = node.get(MENTION_HANDLE)
        if node.get("type") in _MENTION_NODES and isinstance(handle, str):
            return place_mention_node(node, account_for(handle))
        children = node.get("children")
        if isinstance(children, list):
            return {**node, "children": [walk(child) for child in children]}
        return node

    return {**content, "root": walk(content["root"])}


def place_mentions(
    content: Any,
    handles: Iterable[str],
    *,
    people: "PeopleMap",
    member_handles: Mapping[str, int],
) -> Any:
    """``content`` with each mention of a listed handle linked to whoever it
    is here — the account the people step mapped it to, else a member of the
    target initiative with that exact handle (``people.quoted_account``). A
    handle the envelope did not list, or nobody placed, stays a name."""
    from app.services.import_engine.people import quoted_account

    accounts = {
        handle: quoted_account(handle, people=people, member_handles=member_handles)
        for handle in handles
    }
    return place_editor_mentions(content, lambda handle: accounts.get(handle))


def mention_handles_in(payload: Any) -> list[str]:
    """Every handle an envelope, as plain data, lists under
    ``mention_handles`` at any depth — a task's, a comment's, a page's, a
    file's. First-seen order, one entry per spelling."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            listed = node.get("mention_handles")
            if isinstance(listed, list):
                for handle in listed:
                    if isinstance(handle, str) and handle.strip():
                        if handle.strip() not in found:
                            found.append(handle.strip())
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return found


async def detach_envelope_mentions(session: AsyncSession, data: Any) -> None:
    """Rewrite the editor-state mentions in one tool envelope, in place on
    ``data`` (a freshly built envelope dict — the content inside it is never
    edited, only replaced).

    Files, posts and wiki pages carry their bodies as editor states. A
    project envelope's mentions are markdown and are written by
    ``build_project_export`` itself, which is where the text is read.
    """
    if not isinstance(data, dict):
        return
    kind = data.get("type")
    if (
        kind == tool_envelope_type(Tool.file)
        and data.get("file_type") == FileType.lexical
    ):
        holders = [(data, "content")]
    elif kind == tool_envelope_type(Tool.post):
        holders = [(data, "body")]
    elif kind == tool_envelope_type(Tool.wiki):
        holders = [
            (page, "content")
            for page in data.get("pages") or []
            if isinstance(page, dict)
        ] + [
            # A text document filed in it, carried whole inside it.
            (filed["envelope"], "content")
            for filed in data.get("files") or []
            if isinstance(filed, dict)
            and isinstance(filed.get("envelope"), dict)
            and filed["envelope"].get("file_type") == FileType.lexical
        ]
    else:
        return
    wanted = set().union(*(editor_mention_ids(h.get(key)) for h, key in holders))
    if not wanted:
        return
    handles = await load_mention_handles(session, wanted)
    for holder, key in holders:
        content, named = detach_editor_mentions(holder.get(key), handles)
        holder[key] = content
        if named:
            holder["mention_handles"] = named


def _is_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


#: What a markdown mention's name may not hold.
_LABEL_BREAKS = re.compile(r"[\]\n]")


async def mention_namer(
    session: AsyncSession, value: Any, *, missing: str
) -> Callable[[Any], Any]:
    """What writes into a rendered export the name each mention of somebody in
    ``value`` reads as now: their name in the community, or ``missing`` for
    somebody no longer in it. Markdown mentions and editor-state mention nodes
    alike, at any depth, looked up once for all of ``value``. What it returns
    is a copy, as the content inside is usually a loaded row's column."""
    wanted: set[int] = set()

    def collect(value: Any) -> None:
        if isinstance(value, str):
            wanted.update(int(user_id) for _, user_id in STORED_MENTION.findall(value))
        elif isinstance(value, dict):
            if _is_id(value.get("mentionUserId")):
                wanted.add(value["mentionUserId"])
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(value)
    names: dict[int, str] = (
        dict(
            (
                await session.exec(
                    select(GuildMember.id, GuildMember.display_name).where(
                        GuildMember.id.in_(wanted)
                    )
                )
            ).all()
        )
        if wanted
        else {}
    )

    def named(value: Any) -> Any:
        if isinstance(value, str):
            return STORED_MENTION.sub(
                lambda match: (
                    f"@[{_LABEL_BREAKS.sub('', names.get(int(match.group(2)), missing))}]"
                    f"({match.group(2)})"
                ),
                value,
            ).replace(_NOBODY, f"@{missing}")
        if isinstance(value, list):
            return [named(child) for child in value]
        if not isinstance(value, dict):
            return value
        node = {key: named(child) for key, child in value.items()}
        if _is_id(node.get("mentionUserId")):
            name = names.get(node["mentionUserId"], missing)
            node |= {"mentionName": name, "text": name}
        elif node.get("type") in _MENTION_NODES and not node.get("mentionName"):
            node |= {"mentionName": missing, "text": missing}
        return node

    return named
