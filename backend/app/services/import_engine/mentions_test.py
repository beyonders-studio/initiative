"""A mention crossing an export by handle, and placed again on the way in."""

import copy

from app.services.import_engine.mentions import (
    MENTION_HANDLE,
    detach_editor_mentions,
    detach_markdown_mentions,
    editor_mention_ids,
    markdown_mention_ids,
    mention_handles_in,
    mention_namer,
    place_editor_mentions,
)
from app.testing import create_guild, create_guild_membership, create_user


def _mention(name: str, user_id: int | None) -> dict:
    return {
        "type": "mention",
        "version": 1,
        "mentionName": name,
        "mentionUserId": user_id,
        "text": name,
    }


def _editor(*inline: dict) -> dict:
    return {
        "root": {
            "type": "root",
            "children": [{"type": "paragraph", "children": list(inline)}],
        }
    }


def _inline(content: dict) -> list[dict]:
    return content["root"]["children"][0]["children"]


def test_a_markdown_mention_crosses_as_its_handle():
    text = "Ask @[Sam Bee](42) and @[](42), not @[Gone](7) nor @[](8)"

    assert markdown_mention_ids(text) == {42, 7, 8}
    detached, named = detach_markdown_mentions(text, {42: "sam#0042"})

    # Somebody with no handle to give crosses as the name they were written
    # with, where there is one, and no id rides along with any.
    assert detached == "Ask @sam#0042 and @sam#0042, not @Gone nor @[]()"
    assert named == ["sam#0042"]


def test_markdown_with_no_mentions_is_left_alone():
    assert detach_markdown_mentions(None, {1: "a#0001"}) == (None, [])
    assert detach_markdown_mentions("plain", {1: "a#0001"}) == ("plain", [])


def test_an_editor_mention_carries_a_handle_instead_of_an_account():
    content = _editor(
        {"type": "text", "text": "Ask "},
        _mention("Sam Bee", 42),
        _mention("Gone", 7),
    )
    before = copy.deepcopy(content)

    assert editor_mention_ids(content) == {42, 7}
    detached, named = detach_editor_mentions(content, {42: "sam#0042"})

    text, sam, gone = _inline(detached)
    assert text == {"type": "text", "text": "Ask "}
    # The name stays, so the chip still reads as somebody until it is placed.
    assert sam["mentionName"] == "Sam Bee"
    assert sam["mentionUserId"] is None
    assert sam[MENTION_HANDLE] == "sam#0042"
    assert gone["mentionUserId"] is None and MENTION_HANDLE not in gone
    assert named == ["sam#0042"]
    # The loaded row's column is never edited in place.
    assert content == before


def test_an_exported_mention_is_placed_or_left_a_name():
    detached, _ = detach_editor_mentions(
        _editor(_mention("Sam Bee", 42), _mention("Ann", 9)),
        {42: "sam#0042", 9: "ann#0009"},
    )

    placed = place_editor_mentions(
        detached, lambda handle: 5 if handle == "sam#0042" else None
    )

    sam, ann = _inline(placed)
    assert sam["mentionUserId"] == 5 and MENTION_HANDLE not in sam
    # Placed on somebody, it is stored as every mention is: with no name.
    assert (sam["mentionName"], sam["text"]) == ("", "")
    assert ann["mentionUserId"] is None and MENTION_HANDLE not in ann
    assert ann["mentionName"] == "Ann"


def test_a_mention_written_before_handles_crossed_is_left_as_it_was():
    """An envelope from an older export still names an account; placing has
    nothing to say about it."""
    content = _editor(_mention("Sam Bee", 42))

    assert place_editor_mentions(content, lambda _handle: 5) == content


def test_every_listed_handle_is_found_at_any_depth():
    envelope = {
        "tasks": [
            {
                "mention_handles": ["sam#0042"],
                "comments": [{"mention_handles": ["ann#0009", "sam#0042"]}],
            }
        ],
        "pages": [{"mention_handles": [" ", "bo#0003"]}],
    }

    assert mention_handles_in(envelope) == ["sam#0042", "ann#0009", "bo#0003"]


async def test_a_report_names_each_mention_as_it_reads_now(session, reading_as):
    """By the name somebody goes by in the community, and as ``missing`` once
    they are not in it, or where an export could not name them. A mention with
    no account keeps its name."""
    guild = await create_guild(session)
    ada = await create_user(session)
    await create_guild_membership(
        session, user=ada, guild=guild, display_name="Ada Countess"
    )
    gone = await create_user(session)
    content = _editor(
        _mention("", ada.id),
        _mention("Old", gone.id),
        _mention("Bo", None),
        _mention("", None),
    )
    before = copy.deepcopy(content)
    data = {
        "rows": [{"description": f"@[]({ada.id}) and @[Old]({gone.id}), @[]()"}],
        "content": content,
    }

    named = await mention_namer(
        await reading_as(ada.id, guild.id), data, missing="Former member"
    )

    assert named(data) == {
        "rows": [
            {
                "description": f"@[Ada Countess]({ada.id}) and "
                f"@[Former member]({gone.id}), @Former member"
            }
        ],
        "content": _editor(
            _mention("Ada Countess", ada.id),
            _mention("Former member", gone.id),
            _mention("Bo", None),
            _mention("Former member", None),
        ),
    }
    # What it names is a copy: the loaded content is left as it was.
    assert content == before
