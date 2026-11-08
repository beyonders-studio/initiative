"""Board notices: pins that lapse, polls open and closed, receipts, a draft,
and one that goes on reporting a task's column through a live chip.

Dates are spread back across the year on purpose: a board with everything
written today has nothing for the timeline rail to scrub through.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.tools import Tool
from app.models.tenant.post import Post
from app.models.tenant.post_poll import PostPoll, PostPollOption, PostPollVote
from app.models.tenant.post_read import PostRead
from app.models.tenant.resource_grant import ResourceAccessLevel
from seed.common import NOW, Community, chip, lexical, para, share, tag

#: Each notice. ``paragraphs`` is a plain body; ``parts`` is one paragraph of
#: strings and ``(kind, title)`` chips. A draft has ``scheduled_for`` and no
#: ``published_at``. ``general`` defaults to read (``None`` shares with the
#: people in ``shared_with`` only); ``read_by`` never counts the author. A
#: poll's ``votes`` are option indexes by voter.
POSTS: dict[str, list[dict]] = {
    "primary": [
        {
            "name": "Session 12 moved to Saturday",
            "initiative": "strahd",
            "paragraphs": [
                (
                    "The hall is double-booked on Friday, so we are playing Saturday "
                    "instead. Same time, same place, same amount of Barovian drizzle."
                ),
                (
                    "If Saturday does not work for you, say so in the comments and we will "
                    "look at it again."
                ),
            ],
            "created_by": "Dungeon Master",
            "published_at": NOW - timedelta(days=2),
            "pinned_at": NOW - timedelta(days=2),
            "pin_expires_at": NOW + timedelta(days=5),
            "pinned_by": "Dungeon Master",
            "tags": ["quest"],
            "read_by": ["Thorn Ironforge", "Elara Moonwhisper", "Vex Shadowstep"],
        },
        {
            "name": "House rules, in one place at last",
            "initiative": "strahd",
            "paragraphs": [
                (
                    "Inspiration is a d6, not advantage. Death saves are rolled in the "
                    "open. Nobody is allowed to argue with the map."
                ),
                "This one stays at the top so nobody has to go looking for it in the chat.",
            ],
            "created_by": "Dungeon Master",
            "published_at": NOW - timedelta(days=210),
            "pinned_at": NOW - timedelta(days=210),
            "pinned_by": "Dungeon Master",
            "tags": ["lore"],
            "read_by": ["Thorn Ironforge", "Elara Moonwhisper"],
        },
        {
            "name": "Bring dice, we have run out",
            "initiative": "strahd",
            "paragraphs": ["The communal dice bowl is a bowl now. Just a bowl."],
            "created_by": "Thorn Ironforge",
            "published_at": NOW - timedelta(days=95),
            "pinned_at": NOW - timedelta(days=95),
            "pin_expires_at": NOW - timedelta(days=60),
            "pinned_by": "Dungeon Master",
            "read_by": ["Dungeon Master", "Vex Shadowstep"],
        },
        {
            "name": "Which night suits everyone for the finale?",
            "initiative": "strahd",
            "paragraphs": [
                "It is going to run long, so let us pick the night nobody has to leave early."
            ],
            "created_by": "Dungeon Master",
            "published_at": NOW - timedelta(days=6),
            "tags": ["quest"],
            "read_by": ["Thorn Ironforge", "Elara Moonwhisper"],
            "poll": {
                "question": "Which night?",
                "options": ["Friday", "Saturday", "Sunday afternoon"],
                "hide_results": True,
                "closes_at": NOW + timedelta(days=3),
                "votes": {
                    "Thorn Ironforge": [1],
                    "Elara Moonwhisper": [1],
                    "Vex Shadowstep": [0],
                },
            },
        },
        {
            "name": "What are we doing after Barovia?",
            "initiative": "strahd",
            "paragraphs": [
                "Pick as many as you would happily play. Nobody sees who chose what."
            ],
            "created_by": "Dungeon Master",
            "published_at": NOW - timedelta(days=140),
            "read_by": [
                "Thorn Ironforge",
                "Elara Moonwhisper",
                "Vex Shadowstep",
                "Seraphina Dawnlight",
            ],
            "poll": {
                "question": "Next campaign",
                "options": [
                    "Something with a boat",
                    "Heist, city, no dungeons",
                    "Whatever the DM wants",
                ],
                "allows_multiple": True,
                "is_anonymous": True,
                "closes_at": NOW - timedelta(days=120),
                "votes": {
                    "Thorn Ironforge": [0, 2],
                    "Elara Moonwhisper": [1],
                    "Vex Shadowstep": [0],
                    "Seraphina Dawnlight": [2],
                },
            },
        },
        {
            "name": "Where the Amber Temple prep has got to",
            "initiative": "strahd",
            "parts": [
                "Current state of the big one: ",
                ("task", "Find the Sunsword in the Amber Temple"),
                ". Shout if you want to help with the maps.",
            ],
            "created_by": "Dungeon Master",
            "published_at": NOW - timedelta(days=30),
            "read_by": ["Thorn Ironforge"],
        },
        {
            "name": "The hall is booked through March",
            "initiative": "strahd",
            "paragraphs": [
                "Paid, confirmed, receipt filed. No action needed from anybody."
            ],
            "created_by": "Dungeon Master",
            "published_at": NOW - timedelta(days=280),
            "comments_enabled": False,
            "read_by": ["Thorn Ironforge", "Vex Shadowstep"],
        },
        {
            "name": "Quiet word about the Strahd reveal",
            "initiative": "strahd",
            "paragraphs": [
                "Keeping this one to the people who already know so the table stays surprised."
            ],
            "created_by": "Dungeon Master",
            "published_at": NOW - timedelta(days=45),
            "general": None,
            "shared_with": ["Thorn Ironforge", "Elara Moonwhisper"],
            "read_by": ["Thorn Ironforge"],
        },
        {
            "name": "Session 13 prep notes",
            "initiative": "strahd",
            "paragraphs": [
                (
                    "Goes up on the morning of the session so nobody reads it a week early "
                    "and forgets it."
                )
            ],
            "created_by": "Dungeon Master",
            "created_at": NOW - timedelta(days=1),
            "scheduled_for": NOW + timedelta(days=6),
        },
        {
            "name": "Welcome to Phandalin",
            "initiative": "lmop",
            "paragraphs": [
                "New campaign, new board. Anything that needs saying rather than doing goes here.",
                "Character sheets by Thursday, please.",
            ],
            "created_by": "Dungeon Master",
            "published_at": NOW - timedelta(days=320),
            "read_by": ["Thorn Ironforge", "Elara Moonwhisper"],
        },
        {
            "name": "Who is driving to the away game?",
            "initiative": "lmop",
            "paragraphs": ["Two cars, six of us, one very long road."],
            "created_by": "Thorn Ironforge",
            "published_at": NOW - timedelta(days=64),
            "read_by": ["Dungeon Master", "Elara Moonwhisper"],
            "poll": {
                "question": "Seats",
                "options": ["I can drive", "I need a lift", "Making my own way"],
                "votes": {"Dungeon Master": [0], "Elara Moonwhisper": [1]},
            },
        },
    ]
}


def _body(c: Community, d: dict) -> dict:
    if "paragraphs" in d:
        return lexical([para(text) for text in d["paragraphs"]])
    children = [
        chip(part[0], c.tasks[part[1]].id, part[1])
        if isinstance(part, tuple)
        else {"text": part, "type": "text"}
        for part in d["parts"]
    ]
    return lexical([{"children": children, "type": "paragraph"}])


async def seed(c: Community) -> None:
    for d in POSTS.get(c.key, []):
        creator = c.users[d["created_by"]]
        published = d.get("published_at")
        post = Post(
            initiative_id=c.initiatives[d["initiative"]].id,
            name=d["name"],
            body=_body(c, d),
            created_by=creator.id,
            created_at=d.get("created_at") or published or datetime.now(UTC),
            updated_at=published or datetime.now(UTC),
            published_at=published,
            scheduled_for=d.get("scheduled_for"),
            pinned_at=d.get("pinned_at"),
            pin_expires_at=d.get("pin_expires_at"),
            pinned_by=c.users[d["pinned_by"]].id if "pinned_by" in d else None,
            comments_enabled=d.get("comments_enabled", True),
        )
        c.session.add(post)
        await c.session.flush()
        c.ids["posts"].append(post.id)
        share(
            c,
            Tool.post,
            post,
            creator,
            readers=d.get("shared_with", ()),
            general=d.get("general", ResourceAccessLevel.read),
        )
        tag(c, post, d.get("tags", ()))
        for name in d.get("read_by", ()):
            if c.users[name].id != creator.id:
                c.session.add(
                    PostRead(
                        post_id=post.id,
                        user_id=c.users[name].id,
                        read_at=published or datetime.now(UTC),
                    )
                )
                c.ids["post_reads"].append((post.id, name))
        if "poll" in d:
            await _poll(c, post, d["poll"])
    await c.session.flush()


async def _poll(c: Community, post: Post, d: dict) -> None:
    poll = PostPoll(
        post_id=post.id,
        question=d.get("question"),
        allows_multiple=d.get("allows_multiple", False),
        is_anonymous=d.get("is_anonymous", False),
        hide_results=d.get("hide_results", False),
        closes_at=d.get("closes_at"),
    )
    c.session.add(poll)
    await c.session.flush()
    c.ids["post_polls"].append(poll.id)
    options = [
        PostPollOption(poll_id=poll.id, position=index, text=text)
        for index, text in enumerate(d["options"])
    ]
    c.session.add_all(options)
    await c.session.flush()
    for voter, choices in d.get("votes", {}).items():
        for choice in choices:
            c.session.add(
                PostPollVote(
                    poll_id=poll.id,
                    option_id=options[choice].id,
                    user_id=c.users[voter].id,
                )
            )
            c.ids["post_poll_votes"].append((options[choice].id, voter))
