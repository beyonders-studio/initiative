"""Integration tests for platform operator endpoints at /api/v1/operator."""

import csv
import io

import pytest
from sqlmodel import select

from app.models.platform.user import User, UserRole, UserStatus
from app.services.platform import users as users_service
from app.testing.factories import create_user

#: Every test here drives the API through the real app and a real database.


def _parse_csv(body: bytes) -> tuple[list[str], list[list[str]]]:
    """Strip the UTF-8 BOM and parse the CSV body into (headers, rows)."""
    text = body.decode("utf-8")
    text = text.removeprefix("﻿")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    return rows[0], rows[1:]


#: An id no account in the fixture below has.
_NO_SUCH_USER = {"missing": 99998, "gone": 99999}


@pytest.fixture
async def platform_people(acting_user):
    """An operator who may export, and two ordinary accounts to export."""
    return {
        "operator": await acting_user("operator", email="operator@example.com"),
        "one": await acting_user("member", email="alpha@example.com"),
        "two": await acting_user("member", email="bravo@example.com"),
    }


def _export_id(people: dict, name: str) -> int:
    return _NO_SUCH_USER.get(name) or people[name].user.id


async def test_export_platform_users_csv_as_operator(client, platform_people):
    """Operators export every account as a BOM'd CSV attachment, with
    the addresses masked the way the roster it exports masks them."""
    operator = platform_people["operator"]

    response = await client.get(
        "/api/v1/operator/users/export.csv", headers=operator.headers
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in response.headers["content-disposition"]
    assert "platform-users-" in response.headers["content-disposition"]
    assert response.content.startswith("﻿".encode())

    header_row, data_rows = _parse_csv(response.content)
    assert header_row == [
        "user_id",
        "email",
        "handle",
        "platform_role",
        "status",
        "email_verified",
        "created_at",
        "updated_at",
        "timezone",
        "locale",
    ]
    assert {row[1] for row in data_rows} == {
        "o***r@e***m",
        "a***a@e***m",
        "b***o@e***m",
    }
    assert not any("@example.com" in row[1] for row in data_rows)


@pytest.mark.parametrize(
    ("ask", "expect"),
    [
        pytest.param(["one"], ["one"], id="one-id-is-that-account"),
        pytest.param(["one", "two"], ["one", "two"], id="two-ids-are-both-of-them"),
        pytest.param(["missing", "gone"], [], id="no-id-resolves-so-there-is-no-file"),
    ],
)
async def test_export_platform_users_csv_returns_the_accounts_asked_for(
    client, platform_people, ask, expect
):
    """``user_id`` narrows the export to the accounts it names, and a request
    that resolves to nobody is a 404. A single account files under its handle;
    any wider export files under the platform."""
    operator = platform_people["operator"]
    query = "&".join(f"user_id={_export_id(platform_people, name)}" for name in ask)

    response = await client.get(
        f"/api/v1/operator/users/export.csv?{query}", headers=operator.headers
    )

    if not expect:
        assert response.status_code == 404
        return

    assert response.status_code == 200
    _, data_rows = _parse_csv(response.content)
    assert {row[0] for row in data_rows} == {
        str(platform_people[name].user.id) for name in expect
    }

    disposition = response.headers["content-disposition"]
    if len(expect) == 1:
        only = platform_people[expect[0]].user
        # Named by handle, never by address: a filename outlives the download,
        # in a directory listing and in whatever it gets mailed to.
        assert f"user-{only.id}-{only.username}" in disposition
        assert "@" not in disposition
        assert data_rows[0][1] == "a***a@e***m"
    else:
        assert "platform-users-" in disposition


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        pytest.param("deactivate", 400, id="deactivating-is-refused"),
        pytest.param("soft_delete", 400, id="anonymizing-again-is-refused"),
        pytest.param("hard_delete", 200, id="removing-the-row-is-what-is-left"),
    ],
)
async def test_the_only_follow_up_to_anonymizing_is_a_hard_delete(
    client, session, acting_user, action, expected
):
    """An anonymized row holds nothing left to deactivate or to strip, so the
    one action still open on it is removing it."""
    operator = await acting_user("operator")
    target = await create_user(session)
    await users_service.soft_delete_user(session, target.id)

    response = await client.request(
        "DELETE",
        f"/api/v1/operator/users/{target.id}",
        headers=operator.headers,
        json={"action": action},
    )

    assert response.status_code == expected
    if expected == 400:
        assert response.json()["detail"] == "OPERATOR_ALREADY_ANONYMIZED"


@pytest.mark.parametrize(
    ("how", "start_role", "requested"),
    [
        pytest.param("deactivate", UserRole.member, "operator", id="deactivated-up"),
        pytest.param("deactivate", UserRole.operator, "member", id="deactivated-down"),
        pytest.param("anonymize", UserRole.member, "operator", id="anonymized-up"),
        pytest.param("anonymize", UserRole.operator, "member", id="anonymized-down"),
    ],
)
async def test_platform_role_change_rejected_on_inactive_users(
    client, session, acting_user, how, start_role, requested
):
    """Platform role mutations on deactivated or anonymized users are refused
    with ``OPERATOR_CANNOT_CHANGE_ROLE_INACTIVE``, in either direction. The role
    on the target row is unchanged."""
    operator = await acting_user("operator")
    target = await create_user(session, role=start_role)
    if how == "deactivate":
        await users_service.deactivate_user(session, target.id)
    else:
        await users_service.soft_delete_user(session, target.id)
        # Anonymizing demotes the row, so the role under test is put back
        # directly in the database — the endpoint would refuse to set it.
        row = (await session.exec(select(User).where(User.id == target.id))).one()
        row.role = start_role
        session.add(row)
        await session.commit()

    response = await client.patch(
        f"/api/v1/operator/users/{target.id}/platform-role",
        headers=operator.headers,
        json={"role": requested},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "OPERATOR_CANNOT_CHANGE_ROLE_INACTIVE"
    refreshed = (await session.exec(select(User).where(User.id == target.id))).one()
    assert refreshed.role == start_role


async def test_demoting_an_active_operator_completes(client, session, acting_user):
    """Demoting an active operator runs the last-holder check and answers 200,
    with the target's role ending up demoted."""
    deleter = await acting_user("operator")
    target = await create_user(session, role=UserRole.operator)

    response = await client.patch(
        f"/api/v1/operator/users/{target.id}/platform-role",
        headers=deleter.headers,
        json={"role": "member"},
    )
    assert response.status_code == 200, response.text

    refreshed = (await session.exec(select(User).where(User.id == target.id))).one()
    assert refreshed.role == UserRole.member


async def test_platform_roster_masks_addresses(client, acting_user):
    """The roster serves the masked address, not the stored one.

    Asserted on the payload rather than on what the SPA renders, because the
    payload is where the shortening happens.
    """
    owner = await acting_user("owner", email="owner@example.com")
    await acting_user("member", email="user1@example.com")

    response = await client.get("/api/v1/operator/users", headers=owner.headers)

    assert response.status_code == 200
    body = response.json()["items"]
    assert {u["email"] for u in body} == {"o***r@e***m", "u***1@e***m"}
    assert "@example.com" not in response.text


async def test_platform_roster_is_paged_searched_and_sorted(
    client, session, acting_user
):
    """The roster is read a page at a time, searched by handle and sorted on
    the server."""
    owner = await acting_user("owner")
    first = await create_user(session, username="vexquorra", discriminator=42)
    second = await create_user(
        session, username="vexquorrabis", status=UserStatus.suspended
    )
    url = "/api/v1/operator/users"

    async def ids(**params) -> list[int]:
        response = await client.get(url, params=params, headers=owner.headers)
        assert response.status_code == 200, response.text
        return [row["id"] for row in response.json()["items"]]

    page = (
        await client.get(url, params={"page_size": 2}, headers=owner.headers)
    ).json()
    assert page["total_count"] == 3
    assert page["has_next"] is True
    assert [row["id"] for row in page["items"]] == [owner.user.id, first.id]

    assert set(await ids(search="vexquorra")) == {first.id, second.id}
    assert await ids(search="vexquorra#0042") == [first.id]
    assert (await ids(sort_by="status", sort_dir="desc"))[0] == second.id


async def test_operator_mutations_return_masked_addresses(client, acting_user):
    """The single-account operator routes mask too, not just the list.

    Each returns the account it just changed, so each is its own read of an
    address and needs the same shape.
    """
    owner = await acting_user("owner", email="owner@example.com")
    target = await acting_user("member", email="target@example.com")

    role_change = await client.patch(
        f"/api/v1/operator/users/{target.user.id}/platform-role",
        headers=owner.headers,
        json={"role": "support"},
    )
    assert role_change.status_code == 200
    assert role_change.json()["email"] == "t***t@e***m"

    suspend = await client.post(
        f"/api/v1/operator/users/{target.user.id}/suspension",
        headers=owner.headers,
        json={"suspended": True},
    )
    assert suspend.status_code == 200
    assert suspend.json()["email"] == "t***t@e***m"


async def test_own_account_still_reads_its_whole_address(client, acting_user):
    """The one reader entitled to an address is the person it belongs to.

    ``/me`` backs the account screen, where the address is shown so you
    can check which account you are signed in as. Masking it there would be
    withholding it from its owner.
    """
    owner = await acting_user("owner", email="owner@example.com")

    response = await client.get("/api/v1/me", headers=owner.headers)

    assert response.status_code == 200
    assert response.json()["email"] == "owner@example.com"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        pytest.param("GET", "/api/v1/operator/users/export.csv", id="the-export"),
        pytest.param("GET", "/api/v1/operator/users", id="the-roster"),
    ],
)
async def test_the_operator_router_turns_away_an_ordinary_account(
    client, acting_user, method, path
):
    """The operator routes are gated on a capability an ordinary account
    does not hold."""
    a = await acting_user("member")

    response = await client.request(method, path, headers=a.headers)

    assert response.status_code == 403
