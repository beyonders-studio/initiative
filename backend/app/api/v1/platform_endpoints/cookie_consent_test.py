"""An account's cookie answer, and who can reach it.

The browser keeps its own copy — a visitor who has not signed in has no
account. These are about the copy that travels: what a second browser adopts,
and that it belongs to one account alone.
"""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user_cookie_consent import UserCookieConsent

CONSENT = "/api/v1/me/cookie-consent"
ME = "/api/v1/me"


async def test_an_account_that_has_never_answered_carries_no_answer(
    client, acting_user
):
    """Null, not an empty answer: one has not been asked, the other said no,
    and only the first is worth asking again."""
    actor = await acting_user()

    response = await client.get(ME, headers=actor.headers)

    assert response.status_code == 200, response.text
    assert response.json()["cookie_consent"] is None


async def test_an_answer_travels_to_the_next_browser(client, acting_user):
    """The point of the whole thing: answer once, and a browser that has never
    been asked adopts it instead of asking again."""
    actor = await acting_user()

    saved = await client.put(
        CONSENT, json={"granted": ["analytics"], "version": 1}, headers=actor.headers
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["granted"] == ["analytics"]
    assert saved.json()["version"] == 1
    assert saved.json()["decided_at"]

    carried = await client.get(ME, headers=actor.headers)
    assert carried.json()["cookie_consent"]["granted"] == ["analytics"]


async def test_changing_your_mind_replaces_the_answer(client, acting_user):
    """A settings row, not a history: what applies now is the only question."""
    actor = await acting_user()

    await client.put(
        CONSENT,
        json={"granted": ["analytics", "marketing"], "version": 1},
        headers=actor.headers,
    )
    withdrawn = await client.put(
        CONSENT, json={"granted": [], "version": 1}, headers=actor.headers
    )

    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["granted"] == []
    # Allowing nothing is an answer, not the absence of one.
    consent = (await client.get(ME, headers=actor.headers)).json()["cookie_consent"]
    assert consent is not None
    assert consent["granted"] == []


async def test_the_stamp_is_the_servers(client, acting_user):
    """Two browsers comparing their answers compare one clock. A client cannot
    put its own time on the record by sending one."""
    actor = await acting_user()

    first = await client.put(
        CONSENT,
        json={"granted": [], "version": 1, "decided_at": "1999-01-01T00:00:00Z"},
        headers=actor.headers,
    )
    second = await client.put(
        CONSENT, json={"granted": ["analytics"], "version": 1}, headers=actor.headers
    )

    assert first.json()["decided_at"] > "2020"
    assert second.json()["decided_at"] >= first.json()["decided_at"]


async def test_a_category_the_app_has_no_name_for_is_refused(client, acting_user):
    actor = await acting_user()

    response = await client.put(
        CONSENT, json={"granted": ["telepathy"], "version": 1}, headers=actor.headers
    )

    assert response.status_code == 422


async def test_an_answer_belongs_to_one_account(
    client, session: AsyncSession, acting_user
):
    """Two accounts answering differently keep their own answers."""
    a = await acting_user()
    b = await acting_user()

    await client.put(
        CONSENT, json={"granted": ["analytics"], "version": 1}, headers=a.headers
    )
    await client.put(CONSENT, json={"granted": [], "version": 1}, headers=b.headers)

    assert (await client.get(ME, headers=a.headers)).json()["cookie_consent"][
        "granted"
    ] == ["analytics"]
    assert (await client.get(ME, headers=b.headers)).json()["cookie_consent"][
        "granted"
    ] == []
    rows = (await session.exec(select(UserCookieConsent))).all()
    assert {row.user_id for row in rows} >= {a.user.id, b.user.id}


async def test_signing_out_is_the_only_way_in(client):
    """Nobody's answer is readable or writable without a session."""
    assert (
        await client.put(CONSENT, json={"granted": [], "version": 1})
    ).status_code == 401
