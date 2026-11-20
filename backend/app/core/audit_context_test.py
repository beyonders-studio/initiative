"""What a line says about the request it came from."""

import asyncio

import pytest

from app.core import audit_context


@pytest.mark.parametrize("named, community", [("7", 7), ("\u00b2", None), ("x", None)])
def test_a_path_names_its_community_in_ascii_digits_only(named, community):
    scope = {"path_params": {"community_id": named}}
    assert audit_context.RequestContext("r", scope=scope).community_id() == community


async def test_a_pass_is_named_and_each_visit_names_its_own_community():
    """Communities visited at once each keep their own, under the one name
    the pass has."""
    seen = {}

    async def visit(guild_id: int) -> None:
        with audit_context.visiting(guild_id):
            await asyncio.sleep(0)
            context = audit_context.current()
            seen[guild_id] = (context.request_id, context.community_id())

    with audit_context.job("hourly") as job:
        await asyncio.gather(visit(1), visit(2))
        assert audit_context.current() is job
    assert job.request_id.startswith("job-hourly-")
    assert seen == {1: (job.request_id, 1), 2: (job.request_id, 2)}
    assert audit_context.current() is None


@pytest.mark.parametrize(
    ("peer", "kept"),
    [
        ("fe80::1%eth0", "fe80::1"),
        ("2001:DB8::1", "2001:db8::1"),
        ("203.0.113.9", "203.0.113.9"),
        ("testclient", None),
        (None, None),
    ],
)
def test_the_address_is_kept_as_an_inet_column_takes_it(peer, kept):
    """Normalized, without an interface zone, and ``None`` for a peer that
    is not an address."""
    _, token = audit_context.begin(request_id="x", source_ip=peer)
    try:
        assert audit_context.client_ip() == kept
    finally:
        audit_context.end(token)


def test_a_long_user_agent_is_cut_to_a_length():
    context, token = audit_context.begin(request_id="x", user_agent="u" * 5000)
    try:
        assert context.user_agent is not None
        assert len(context.user_agent) == audit_context.MAX_USER_AGENT
    finally:
        audit_context.end(token)


def test_a_line_that_does_not_need_the_caller_names_only_the_request():
    """Which request it was, and not where the person was sitting."""
    _, token = audit_context.begin(
        request_id="abc123", source_ip="203.0.113.7", user_agent="Firefox/1"
    )
    try:
        assert audit_context.envelope_context(caller=False) == {"request_id": "abc123"}
    finally:
        audit_context.end(token)


def test_a_granted_request_names_the_grant_that_serves_it():
    _, token = audit_context.begin(request_id="x")
    try:
        audit_context.note_grant(
            actor_user_id=42,
            guild_id=7,
            grant_id=88,
            access_level="read_write",
            settings_grant_id=89,
            settings_level="superadmin",
            break_glass=True,
        )
        context = audit_context.current()
        assert context.is_privileged
        assert context.actor_user_id == 42
        assert context.guild_id == 7
        assert audit_context.envelope_context(caller=True) == {
            "request_id": "x",
            "source_ip": None,
            "user_agent": None,
            "grant_id": 88,
            "access_level": "read_write",
            "settings_grant_id": 89,
            "settings_level": "superadmin",
            "break_glass": True,
        }
    finally:
        audit_context.end(token)


def test_the_grant_that_admitted_the_request_is_the_one_kept():
    """A request may route into a second community part-way through. What let
    it in is what it was admitted on, not what it touched afterwards."""
    _, token = audit_context.begin(request_id="x")
    try:
        audit_context.note_grant(actor_user_id=1, guild_id=7, grant_id=88)
        audit_context.note_grant(actor_user_id=1, guild_id=9, grant_id=99)
        context = audit_context.current()
        assert (context.guild_id, context.grant_id) == (7, 88)
    finally:
        audit_context.end(token)


def test_noting_a_grant_outside_a_request_does_nothing():
    """The socket paths route a session with no request open; they record no
    line, so there is nothing for this to reach."""
    audit_context.note_grant(actor_user_id=1, guild_id=7, grant_id=88)
    assert audit_context.current() is None


@pytest.mark.parametrize(
    "supplied",
    ["abc-123", "A.B_c", "0", "f" * audit_context.MAX_REQUEST_ID],
)
def test_an_id_of_letters_digits_and_separators_is_kept(supplied):
    assert audit_context.clean_request_id(supplied) == supplied


@pytest.mark.parametrize(
    "supplied",
    [
        None,
        "",
        "has space",
        "quote'd",
        "new\nline",
        '{"json":1}',
        "f" * (audit_context.MAX_REQUEST_ID + 1),
    ],
)
def test_anything_else_is_not_an_id(supplied):
    """The id reaches a log line as it arrived, so it is held to a shape."""
    assert audit_context.clean_request_id(supplied) is None
