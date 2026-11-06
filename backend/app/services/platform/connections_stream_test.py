"""The connections channel: who gets poked, and — mostly — who does not.

The channel is content-free, so what is worth asserting is the addressing. Half
of these are about an account that must hear nothing: a frame is as much a tell
as a notification, and an ignored account is told neither that it happened nor
that it was lifted.
"""

import json
from typing import Any


from app.models.platform.contact_grant import ContactGrantKind
from app.models.platform.user_dm_settings import DmPolicy
from app.models.platform.user_ignore import UserIgnore
from app.services.platform import contact_grants as contact_grants_service
from app.services.platform import (
    connections_stream,
    notify_bus,
    user_ignores,
    user_stream,
)
from app.testing.sockets import FakeWebSocket, settle
from app.testing import create_user
from sqlalchemy import text


async def _socket_for(account_socket, user) -> FakeWebSocket:
    return account_socket(user.id)


def _connections_frames(socket: FakeWebSocket) -> list[dict]:
    return [f for f in socket.sent if f.get("resource") == connections_stream.RESOURCE]


async def _as(session, user) -> None:
    await session.exec(
        text("SELECT set_config('app.current_user_id', :v, true)").bindparams(
            v=str(user.id)
        )
    )


async def _open(session, user, policy: DmPolicy = DmPolicy.public) -> None:
    await session.exec(
        text(
            "UPDATE public.user_dm_settings SET dm_policy = CAST(:p AS user_dm_policy) "
            "WHERE user_id = :u"
        ).bindparams(p=policy.value, u=user.id)
    )


async def test_a_request_pokes_both_parties(session, account_socket):
    ada = await create_user(session)
    bram = await create_user(session)
    await _open(session, ada)
    await _open(session, bram)
    await session.commit()

    to_ada = await _socket_for(account_socket, ada)
    to_bram = await _socket_for(account_socket, bram)

    await _as(session, bram)
    await contact_grants_service.request(
        session, actor_id=bram.id, target_id=ada.id, kind=ContactGrantKind.connection
    )
    await settle()

    assert _connections_frames(to_ada), (
        "the recipient is told there is something to see"
    )
    assert _connections_frames(to_bram), "and the requester that theirs is pending"


async def test_an_ignored_requester_pokes_only_themselves(session, account_socket):
    """The row is stored and stays out of sight, so no frame says otherwise."""
    ada = await create_user(session)
    bram = await create_user(session)
    await _open(session, ada)
    await _open(session, bram)
    session.add(UserIgnore(user_id=ada.id, ignored_user_id=bram.id))
    await session.commit()

    to_ada = await _socket_for(account_socket, ada)
    to_bram = await _socket_for(account_socket, bram)

    await _as(session, bram)
    await contact_grants_service.request(
        session, actor_id=bram.id, target_id=ada.id, kind=ContactGrantKind.connection
    )
    await settle()

    assert _connections_frames(to_ada) == []
    assert _connections_frames(to_bram), "and it looks entirely ordinary to them"


async def test_ignoring_pokes_the_holder_and_nobody_else(session, account_socket):
    ada = await create_user(session)
    bram = await create_user(session)
    await session.commit()

    to_ada = await _socket_for(account_socket, ada)
    to_bram = await _socket_for(account_socket, bram)

    await user_ignores.add(session, user_id=ada.id, ignored_user_id=bram.id)
    await settle()

    assert _connections_frames(to_ada)
    assert _connections_frames(to_bram) == []


async def test_lifting_an_ignore_pokes_the_holder_and_nobody_else(
    session, account_socket
):
    """The other end of the same silence: stopping is as quiet as starting."""
    ada = await create_user(session)
    bram = await create_user(session)
    await user_ignores.add(session, user_id=ada.id, ignored_user_id=bram.id)
    await session.commit()

    to_ada = await _socket_for(account_socket, ada)
    to_bram = await _socket_for(account_socket, bram)

    await user_ignores.remove(session, user_id=ada.id, ignored_user_id=bram.id)
    await settle()

    assert _connections_frames(to_ada)
    assert _connections_frames(to_bram) == []


async def test_the_frame_carries_nothing(session, account_socket):
    ada = await create_user(session)
    bram = await create_user(session)
    await session.commit()
    to_ada = await _socket_for(account_socket, ada)

    await user_ignores.add(session, user_id=ada.id, ignored_user_id=bram.id)
    await settle()

    frame = _connections_frames(to_ada)[0]
    assert frame["resource"] == "connections"
    assert frame["ids"] == {}
    assert set(frame) == {"resource", "action", "ids", "timestamp"}


async def test_a_fan_out_publishes_for_everyone_it_names(
    session, account_socket, monkeypatch
):
    """Not narrowed to this worker's own sockets, and one notice for all.

    That narrowing would have to happen before ``publish``, which is also what
    puts a frame on the cross-worker bus — so an account connected only to
    another worker would never be published for. Here ``away`` stands in for
    that account: it holds no socket on this process, and the frame is still
    sent for it, in the same notice as ``here``.
    """
    here = await create_user(session)
    away = await create_user(session)
    await session.commit()
    to_here = await _socket_for(account_socket, here)

    notices: list[dict[str, Any]] = []

    async def _capture(_channel: str, payload: str) -> None:
        notices.append(json.loads(payload))

    monkeypatch.setattr(notify_bus, "notify", _capture)

    user_stream.queue_signals(session, [here.id, away.id], connections_stream.RESOURCE)
    await session.commit()
    await settle()

    assert _connections_frames(to_here)
    assert [notice["user_ids"] for notice in notices] == [[here.id, away.id]]
