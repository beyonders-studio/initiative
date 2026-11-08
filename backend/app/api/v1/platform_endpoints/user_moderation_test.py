"""What a moderator may do to an account, and everything they may not.

Three actions: take a picture down, change a username, freeze the account. Each
is gated on a platform capability, each records itself, each tells the person.
Nothing else about an account is a moderator's to change, and none of it needs
a PAM grant — these are platform actions about an account, not access to a
guild's content.
"""

from datetime import UTC

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.main import app
from app.models.platform.guild import CommunityRole
from app.models.platform.notification import Notification, NotificationType
from app.models.platform.user import UserRole, UserStatus
from app.testing import (
    create_guild,
    create_guild_membership,
    create_user,
    drain_notices,
    emitted,
)
from app.testing.factories import get_auth_headers


async def _notification_types(session: AsyncSession, user_id: int) -> set[str]:
    await drain_notices()
    rows = (
        await session.exec(select(Notification).where(Notification.user_id == user_id))
    ).all()
    return {row.type for row in rows}


def _audit_entries(capfd, subject_id: int) -> list[dict]:
    return [row for row in emitted(capfd) if row["target_user_id"] == subject_id]


class TestRenaming:
    async def test_a_moderator_sets_the_name_part(
        self, client: AsyncClient, session: AsyncSession
    ):
        moderator = await create_user(session, role=UserRole.moderator)
        subject = await create_user(session, username="unsuitable", discriminator=42)

        response = await client.patch(
            f"/api/v1/operator/users/{subject.id}/username",
            headers=get_auth_headers(moderator),
            json={"username": "renamed"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["username"] == "renamed"
        # The number is drawn, not chosen — not by its owner, and not by a
        # moderator either. It survives the rename.
        assert response.json()["discriminator"] == 42

    async def test_the_new_name_is_validated_like_any_other(
        self, client: AsyncClient, session: AsyncSession
    ):
        moderator = await create_user(session, role=UserRole.moderator)
        subject = await create_user(session)

        response = await client.patch(
            f"/api/v1/operator/users/{subject.id}/username",
            headers=get_auth_headers(moderator),
            json={"username": "owner"},
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "USERNAME_RESERVED"

    async def test_the_subject_cannot_spend_a_pick_undoing_it(
        self, client: AsyncClient, session: AsyncSession
    ):
        moderator = await create_user(session, role=UserRole.moderator)
        subject = await create_user(session, username_chosen=False)

        await client.patch(
            f"/api/v1/operator/users/{subject.id}/username",
            headers=get_auth_headers(moderator),
            json={"username": "assigned-name"},
        )

        claim = await client.patch(
            "/api/v1/me/username",
            headers=get_auth_headers(subject),
            json={"username": "back-to-mine"},
        )
        assert claim.status_code == 409

    async def test_the_person_is_told_and_the_change_is_recorded(
        self, client: AsyncClient, session: AsyncSession, capfd
    ):
        moderator = await create_user(session, role=UserRole.moderator)
        subject = await create_user(session, username="before", discriminator=7)
        subject_id, moderator_id = subject.id, moderator.id
        capfd.readouterr()

        await client.patch(
            f"/api/v1/operator/users/{subject_id}/username",
            headers=get_auth_headers(moderator),
            json={"username": "after"},
        )

        entry = _audit_entries(capfd, subject_id)[0]
        assert NotificationType.username_changed.value in await _notification_types(
            session, subject_id
        )
        assert entry["event_type"] == "user.username_changed"
        assert entry["actor_user_id"] == moderator_id
        assert entry["detail"] == {}

    async def test_below_moderator_is_refused(
        self, client: AsyncClient, session: AsyncSession
    ):
        actor = await create_user(session)
        subject = await create_user(session)

        response = await client.patch(
            f"/api/v1/operator/users/{subject.id}/username",
            headers=get_auth_headers(actor),
            json={"username": "nope"},
        )
        assert response.status_code == 403


class TestSuspension:
    @pytest.fixture
    async def moderator_and_member(self, session):
        moderator = await create_user(session, role=UserRole.moderator)
        member = await create_user(session)
        guild = await create_guild(session, creator=member)
        await create_guild_membership(
            session, user=member, guild=guild, role=CommunityRole.admin
        )
        return moderator, member, guild

    async def _suspend(self, client, moderator, member, suspended=True, reason=None):
        return await client.post(
            f"/api/v1/operator/users/{member.id}/suspension",
            headers=get_auth_headers(moderator),
            json={"suspended": suspended, **({"reason": reason} if reason else {})},
        )

    async def test_it_freezes_and_thaws(self, client, session, moderator_and_member):
        moderator, member, _guild = moderator_and_member

        frozen = await self._suspend(client, moderator, member)
        assert frozen.status_code == 200, frozen.text
        assert frozen.json()["status"] == "suspended"

        thawed = await self._suspend(client, moderator, member, suspended=False)
        assert thawed.json()["status"] == "active"

    async def test_a_suspended_account_still_signs_in(
        self, client, session, moderator_and_member
    ):
        """Being able to sign in is how its holder reaches their own account,
        and the only reason telling them anything works."""
        moderator, member, _guild = moderator_and_member
        await self._suspend(client, moderator, member)

        response = await client.get("/api/v1/me", headers=get_auth_headers(member))

        assert response.status_code == 200
        assert response.json()["status"] == "suspended"

    async def test_it_reaches_no_guild(self, client, session, moderator_and_member):
        moderator, member, guild = moderator_and_member
        before = await client.get(
            f"/api/v1/c/{guild.id}/users/", headers=get_auth_headers(member)
        )
        assert before.status_code == 200

        await self._suspend(client, moderator, member)

        after = await client.get(
            f"/api/v1/c/{guild.id}/users/", headers=get_auth_headers(member)
        )
        # Refused before any guild is looked at: the account is in time out.
        assert after.status_code == 403
        assert after.json()["detail"] == "ACCOUNT_SUSPENDED"

    async def test_its_guild_list_is_refused(
        self, client, session, moderator_and_member
    ):
        moderator, member, _guild = moderator_and_member
        await self._suspend(client, moderator, member)

        response = await client.get(
            "/api/v1/communities/", headers=get_auth_headers(member)
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "ACCOUNT_SUSPENDED"

    async def test_nothing_is_taken_away(self, client, session, moderator_and_member):
        """Suspension writes one column. Lifting it restores the account
        whole, which is what makes it different from deactivation."""
        moderator, member, guild = moderator_and_member

        await self._suspend(client, moderator, member)
        await self._suspend(client, moderator, member, suspended=False)

        response = await client.get(
            f"/api/v1/c/{guild.id}/users/", headers=get_auth_headers(member)
        )
        assert response.status_code == 200
        assert member.id in {row["id"] for row in response.json()["items"]}

    async def test_they_vanish_from_the_roster(
        self, client, session, moderator_and_member
    ):
        moderator, member, guild = moderator_and_member
        onlooker = await create_user(session)
        await create_guild_membership(
            session, user=onlooker, guild=guild, role=CommunityRole.member
        )

        await self._suspend(client, moderator, member)

        response = await client.get(
            f"/api/v1/c/{guild.id}/users/", headers=get_auth_headers(onlooker)
        )
        assert member.id not in {row["id"] for row in response.json()["items"]}

    async def test_they_vanish_from_the_picker(
        self, client, session, moderator_and_member
    ):
        moderator, member, guild = moderator_and_member
        onlooker = await create_user(session)
        await create_guild_membership(
            session, user=onlooker, guild=guild, role=CommunityRole.member
        )

        await self._suspend(client, moderator, member)

        response = await client.get(
            f"/api/v1/c/{guild.id}/users/search", headers=get_auth_headers(onlooker)
        )
        assert member.id not in {row["id"] for row in response.json()["items"]}

    async def test_the_person_is_told_with_the_reason(
        self, client, session, moderator_and_member
    ):
        moderator, member, _guild = moderator_and_member

        await self._suspend(client, moderator, member, reason="Terms of use")

        assert NotificationType.account_suspended.value in await _notification_types(
            session, member.id
        )

    async def test_both_directions_are_recorded(
        self, client, session, moderator_and_member, capfd
    ):
        moderator, member, _guild = moderator_and_member
        member_id = member.id
        capfd.readouterr()

        await self._suspend(client, moderator, member, reason="Terms of use")
        await self._suspend(client, moderator, member, suspended=False)

        entries = _audit_entries(capfd, member_id)
        assert {e["event_type"]: e["detail"] for e in entries} == {
            "user.suspended": {"reason_given": True},
            "user.unsuspended": {"reason_given": False},
        }

    async def test_a_moderator_cannot_suspend_themselves(
        self, client, session, moderator_and_member
    ):
        moderator, _member, _guild = moderator_and_member

        response = await client.post(
            f"/api/v1/operator/users/{moderator.id}/suspension",
            headers=get_auth_headers(moderator),
            json={"suspended": True},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "OPERATOR_CANNOT_SUSPEND_SELF"

    async def test_a_closed_account_is_not_frozen(self, client, session):
        """Thawing it later would quietly reopen an account its owner closed."""
        moderator = await create_user(session, role=UserRole.moderator)
        closed = await create_user(session, status=UserStatus.deactivated)

        response = await client.post(
            f"/api/v1/operator/users/{closed.id}/suspension",
            headers=get_auth_headers(moderator),
            json={"suspended": True},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "OPERATOR_CANNOT_SUSPEND_INACTIVE"

    @pytest.mark.parametrize(
        ("actor_role", "subject_role"),
        [
            (UserRole.moderator, UserRole.operator),
            (UserRole.moderator, UserRole.owner),
            (UserRole.operator, UserRole.owner),
        ],
    )
    async def test_an_account_that_outranks_you_is_refused(
        self, client, session, actor_role, subject_role
    ):
        actor = await create_user(session, role=actor_role)
        subject = await create_user(session, role=subject_role)

        response = await client.post(
            f"/api/v1/operator/users/{subject.id}/suspension",
            headers=get_auth_headers(actor),
            json={"suspended": True},
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "OPERATOR_CANNOT_SUSPEND_HIGHER_ROLE"

    async def test_below_moderator_is_refused(self, client, session):
        actor = await create_user(session)
        subject = await create_user(session)

        response = await client.post(
            f"/api/v1/operator/users/{subject.id}/suspension",
            headers=get_auth_headers(actor),
            json={"suspended": True},
        )
        assert response.status_code == 403


class TestLiftingASignInLock:
    async def test_support_lifts_a_lock(self, client, session):
        from app.services.auth import sign_in_locks

        support = await create_user(session, role=UserRole.support)
        subject = await create_user(session)
        for _ in range(sign_in_locks.LOCK_AFTER_FAILURES):
            await sign_in_locks.record_failure(session, subject.id)
        await session.commit()
        assert await sign_in_locks.is_locked(session, subject.id)

        lifted = await client.delete(
            f"/api/v1/operator/users/{subject.id}/sign-in-lock",
            headers=get_auth_headers(support),
        )
        assert lifted.status_code == 200, lifted.text
        assert lifted.json()["sign_in_locked_until"] is None
        assert not await sign_in_locks.is_locked(session, subject.id)

        again = await client.delete(
            f"/api/v1/operator/users/{subject.id}/sign-in-lock",
            headers=get_auth_headers(support),
        )
        assert again.status_code == 400
        assert again.json()["detail"] == "USER_SIGN_IN_NOT_LOCKED"

    async def test_a_moderator_cannot(self, client, session):
        moderator = await create_user(session, role=UserRole.moderator)
        subject = await create_user(session)
        response = await client.delete(
            f"/api/v1/operator/users/{subject.id}/sign-in-lock",
            headers=get_auth_headers(moderator),
        )
        assert response.status_code == 403


class TestRevokingApiKeys:
    async def test_support_switches_off_the_keys_that_still_work(
        self, client, session, capfd
    ):
        from datetime import datetime, timedelta

        from app.services.platform import api_keys as api_keys_service

        support = await create_user(session, role=UserRole.support)
        subject = await create_user(session)
        secret, _key = await api_keys_service.create_api_key(
            session, user=subject, name="ci"
        )
        await api_keys_service.create_api_key(
            session,
            user=subject,
            name="old",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        listed = await client.get(
            "/api/v1/operator/users", headers=get_auth_headers(support)
        )
        row = next(u for u in listed.json()["items"] if u["id"] == subject.id)
        # The expired key no longer works, so it is not one to revoke.
        assert row["api_key_count"] == 1

        revoked = await client.delete(
            f"/api/v1/operator/users/{subject.id}/api-keys",
            headers=get_auth_headers(support),
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["api_key_count"] == 0
        assert await api_keys_service.authenticate_api_key(session, secret) is None
        assert [
            (e["actor_user_id"], e["target_user_id"])
            for e in emitted(capfd, AuditEventType.API_KEY_REVOKED)
        ] == [(support.id, subject.id)]

        again = await client.delete(
            f"/api/v1/operator/users/{subject.id}/api-keys",
            headers=get_auth_headers(support),
        )
        assert again.status_code == 400
        assert again.json()["detail"] == "USER_NO_LIVE_API_KEYS"

    async def test_a_moderator_cannot(self, client, session):
        moderator = await create_user(session, role=UserRole.moderator)
        subject = await create_user(session)
        response = await client.delete(
            f"/api/v1/operator/users/{subject.id}/api-keys",
            headers=get_auth_headers(moderator),
        )
        assert response.status_code == 403


class TestNothingElse:
    """The operator surface writes a fixed set of things about an account, and
    each one is gated deliberately. One more appearing here is a decision, not
    an accident — this is what makes it one."""

    def test_the_operator_router_writes_only_what_it_should(self):
        writes = {
            (route.path, verb)
            for route in app.routes
            if getattr(route, "path", "").startswith("/api/v1/operator/users")
            for verb in getattr(route, "methods", set())
            if verb in {"POST", "PATCH", "PUT", "DELETE"}
        }

        assert writes == {
            # Moderator (content.moderate).
            ("/api/v1/operator/users/{user_id}/avatar", "DELETE"),
            ("/api/v1/operator/users/{user_id}/username", "PATCH"),
            # Names in communities, status line, decorations: each cleared,
            # never set, like the picture.
            ("/api/v1/operator/users/{user_id}/profile/{field}", "DELETE"),
            ("/api/v1/operator/users/{user_id}/suspension", "POST"),
            # Support (users.age_unblock): getting somebody back into their
            # account after a mistyped birth year is support work, not a
            # moderation decision.
            ("/api/v1/operator/users/{user_id}/age-block", "DELETE"),
            # Support (users.manage): account recovery.
            # Ends every session; its holder signs in again.
            ("/api/v1/operator/users/{user_id}/sessions", "DELETE"),
            # Turns password and code sign-in back on after wrong answers.
            ("/api/v1/operator/users/{user_id}/sign-in-lock", "DELETE"),
            # Switches off the account's API keys; its holder can make new ones.
            ("/api/v1/operator/users/{user_id}/api-keys", "DELETE"),
            ("/api/v1/operator/users/{user_id}/reactivate", "POST"),
            ("/api/v1/operator/users/{user_id}/restore", "POST"),
            # Sends the holder a link; it never sets a password.
            ("/api/v1/operator/users/{user_id}/reset-password", "POST"),
            # Sends the sign-up confirmation letter again; it never marks an
            # address confirmed.
            ("/api/v1/operator/users/{user_id}/verification-email", "POST"),
            # Clears a second factor the holder can no longer present — the
            # lost-phone path. Like the reset above it is a removal, never a
            # read: nothing here hands back the seed or the recovery codes.
            ("/api/v1/operator/users/{user_id}/second-factor", "DELETE"),
            # Operator and above, deliberately out of a moderator's reach.
            ("/api/v1/operator/users/{user_id}/platform-role", "PATCH"),
            ("/api/v1/operator/users/{user_id}", "DELETE"),
        }

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("DELETE", "/avatar", None),
            ("PATCH", "/username", {"username": "renamed"}),
            ("DELETE", "/profile/custom_status", None),
            ("DELETE", "/sessions", None),
            ("DELETE", "/sign-in-lock", None),
            ("DELETE", "/api-keys", None),
            ("POST", "/reactivate", None),
            ("POST", "/restore", None),
            ("DELETE", "/second-factor", None),
            ("POST", "/reset-password", None),
            ("POST", "/verification-email", None),
            ("DELETE", "/age-block", None),
            ("GET", "/deletion-eligibility", None),
            ("DELETE", "", {"action": "hard_delete"}),
        ],
    )
    async def test_an_account_that_outranks_you_is_out_of_reach(
        self, client, session, method, path, body
    ):
        """Every account action holds the rank bound a suspension and a role
        change hold."""
        operator = await create_user(session, role=UserRole.operator)
        owner = await create_user(session, role=UserRole.owner)

        response = await client.request(
            method,
            f"/api/v1/operator/users/{owner.id}{path}",
            headers=get_auth_headers(operator),
            json=body,
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "OPERATOR_CANNOT_MANAGE_HIGHER_ROLE"

    async def test_reactivate_reopens_only_a_deactivated_account(
        self, client, session, capfd
    ):
        """A suspension and a pending deletion have their own ways back; the one
        reactivate takes is recorded."""
        support = await create_user(session, role=UserRole.support)
        headers = get_auth_headers(support)
        for held in (UserStatus.suspended, UserStatus.deleted):
            subject = await create_user(session, status=held)
            response = await client.post(
                f"/api/v1/operator/users/{subject.id}/reactivate", headers=headers
            )
            assert response.status_code == 409
            assert response.json()["detail"] == "OPERATOR_USER_NOT_DEACTIVATED"

        closed = await create_user(session, status=UserStatus.deactivated)
        response = await client.post(
            f"/api/v1/operator/users/{closed.id}/reactivate", headers=headers
        )
        assert response.status_code == 200
        assert response.json()["status"] == "active"
        assert [e["event_type"] for e in _audit_entries(capfd, closed.id)] == [
            "user.reactivated"
        ]


class TestTheAggregateRoutes:
    """``/me/*`` reads content across every guild without going through the
    guild path, so it needs the same answer that path gives."""

    @pytest.fixture
    async def suspended_with_work(self, client, session, acting_user):
        moderator = await create_user(session, role=UserRole.moderator)
        a = await acting_user(
            guild_role=CommunityRole.admin, initiative=True, project=True
        )
        return moderator, a

    async def test_my_tasks_is_refused_once_suspended(
        self, client, session, suspended_with_work
    ):
        moderator, a = suspended_with_work
        before = await client.get("/api/v1/me/tasks", headers=a.headers)
        assert before.status_code == 200

        await client.post(
            f"/api/v1/operator/users/{a.user.id}/suspension",
            headers=get_auth_headers(moderator),
            json={"suspended": True},
        )

        after = await client.get("/api/v1/me/tasks", headers=a.headers)
        assert after.status_code == 403
        assert after.json()["detail"] == "ACCOUNT_SUSPENDED"

    async def test_my_projects_is_refused_once_suspended(
        self, client, session, suspended_with_work
    ):
        moderator, a = suspended_with_work

        await client.post(
            f"/api/v1/operator/users/{a.user.id}/suspension",
            headers=get_auth_headers(moderator),
            json={"suspended": True},
        )

        response = await client.get("/api/v1/me/projects", headers=a.headers)
        assert response.status_code == 403
        assert response.json()["detail"] == "ACCOUNT_SUSPENDED"

    async def test_tabs_are_refused_once_suspended(
        self, client, session, suspended_with_work
    ):
        """``/me/personal-items`` builds its own guild list rather than going through
        ``member_guild_ids``; the account gate stops it before either."""
        moderator, a = suspended_with_work

        await client.post(
            f"/api/v1/operator/users/{a.user.id}/suspension",
            headers=get_auth_headers(moderator),
            json={"suspended": True},
        )

        response = await client.get(
            "/api/v1/me/personal-items?mark=view", headers=a.headers
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "ACCOUNT_SUSPENDED"

    async def test_and_it_all_comes_back(self, client, session, suspended_with_work):
        """The memberships were never dropped, so lifting the suspension is the
        whole restoration."""
        moderator, a = suspended_with_work

        for suspended in (True, False):
            await client.post(
                f"/api/v1/operator/users/{a.user.id}/suspension",
                headers=get_auth_headers(moderator),
                json={"suspended": suspended},
            )

        response = await client.get("/api/v1/me/projects", headers=a.headers)
        assert response.json()["items"] != []


class TestTimeOut:
    """A suspended account signs in to its time-out screen and reaches the
    allow-list — its own profile, sessions and notifications — and nothing
    else, whatever its platform rung."""

    @pytest.fixture
    async def suspended(self, client, session):
        moderator = await create_user(session, role=UserRole.moderator)
        subject = await create_user(session, role=UserRole.moderator)
        response = await client.post(
            f"/api/v1/operator/users/{subject.id}/suspension",
            headers=get_auth_headers(moderator),
            json={"suspended": True},
        )
        assert response.status_code == 200, response.text
        return subject

    async def test_the_allow_list_answers(self, client, suspended):
        headers = get_auth_headers(suspended)
        for path in (
            "/api/v1/me",
            "/api/v1/me/time-out",
            "/api/v1/auth/sessions",
            "/api/v1/notifications/",
        ):
            response = await client.get(path, headers=headers)
            assert response.status_code == 200, (path, response.text)

    async def test_it_holds_no_rung(self, client, suspended):
        headers = get_auth_headers(suspended)
        me = (await client.get("/api/v1/me", headers=headers)).json()
        assert me["status"] == "suspended"
        assert me["capabilities"] == []
        assert me["can_create_communities"] is False

        response = await client.get("/api/v1/operator/users", headers=headers)
        assert response.status_code == 403

    async def test_everything_else_is_refused(self, client, suspended):
        headers = get_auth_headers(suspended)
        for method, path, body in (
            ("patch", "/api/v1/me", {"timezone": "UTC"}),
            ("post", "/api/v1/communities/", {"name": "Mine"}),
            ("post", "/api/v1/me/delete-account", {}),
            ("get", "/api/v1/me/people", None),
            ("get", "/api/v1/me/tasks", None),
        ):
            call = getattr(client, method)
            response = await (
                call(path, headers=headers, json=body)
                if body is not None
                else call(path, headers=headers)
            )
            assert response.status_code == 403, (path, response.text)
            assert response.json()["detail"] == "ACCOUNT_SUSPENDED", path

    async def test_the_screen_names_the_moderation_contact(
        self, client, session, suspended
    ):
        from app.models.platform.app_setting import AppSetting

        row = await session.get(AppSetting, 1) or AppSetting(id=1)
        row.intake_general_contact = "ops@example.com"
        row.intake_contacts = {"moderation": "trust@example.com"}
        session.add(row)
        await session.commit()

        body = (
            await client.get("/api/v1/me/time-out", headers=get_auth_headers(suspended))
        ).json()
        assert body["contact_email"] == "trust@example.com"
        assert body["since"] is not None

    async def test_the_screen_gives_this_suspensions_reason(self, client, session):
        moderator = await create_user(session, role=UserRole.moderator)
        subject = await create_user(session)
        path = f"/api/v1/operator/users/{subject.id}/suspension"
        moderating = get_auth_headers(moderator)

        async def _reason():
            screen = await client.get(
                "/api/v1/me/time-out", headers=get_auth_headers(subject)
            )
            return screen.json()["reason"]

        await client.post(
            path,
            headers=moderating,
            json={"suspended": True, "reason": "Spam in three communities"},
        )
        assert await _reason() == "Spam in three communities"

        # A later suspension that gives no reason does not show the last one's.
        await client.post(path, headers=moderating, json={"suspended": False})
        await client.post(path, headers=moderating, json={"suspended": True})
        assert await _reason() is None


class TestPlatformRole:
    """Granting a rung is an operator's job, and the log says so.

    It sat alongside these actions for a long time without recording itself,
    which made it the one change to an account that left no trace.
    """

    async def test_a_role_change_is_recorded(
        self, client: AsyncClient, session: AsyncSession, capfd
    ):
        operator = await create_user(session, role=UserRole.operator)
        operator_id = operator.id
        subject = await create_user(session)
        subject_id = subject.id
        capfd.readouterr()

        response = await client.patch(
            f"/api/v1/operator/users/{subject_id}/platform-role",
            headers=get_auth_headers(operator),
            json={"role": "support"},
        )
        assert response.status_code == 200, response.text

        entries = _audit_entries(capfd, subject_id)
        assert [entry["event_type"] for entry in entries] == [
            "user.platform_role_changed"
        ]
        entry = entries[0]
        # The two rungs it moved between, so the log reads without the reader
        # having to reconstruct the account's history.
        assert entry["detail"] == {"from": "member", "to": "support"}
        assert entry["actor_user_id"] == operator_id
        # Operator work, not moderation.
        assert entry["category"] == "platform"

    async def test_a_refused_change_records_nothing(
        self, client: AsyncClient, session: AsyncSession, capfd
    ):
        """The write and its record share a transaction, so a refusal leaves
        neither."""
        operator = await create_user(session, role=UserRole.operator)
        subject = await create_user(session)
        subject_id = subject.id
        capfd.readouterr()

        response = await client.patch(
            f"/api/v1/operator/users/{subject_id}/platform-role",
            headers=get_auth_headers(operator),
            json={"role": "owner"},
        )

        assert response.status_code == 403
        assert _audit_entries(capfd, subject_id) == []


async def test_clearing_part_of_a_profile_tells_its_holder_what_went(
    client: AsyncClient, session: AsyncSession
):
    moderator = await create_user(session, role=UserRole.moderator)
    subject = await create_user(session)
    subject_id = subject.id

    response = await client.delete(
        f"/api/v1/operator/users/{subject_id}/profile/custom_status",
        headers=get_auth_headers(moderator),
    )
    assert response.status_code == 200, response.text

    await drain_notices()
    (line,) = (
        await session.exec(
            select(Notification)
            .where(Notification.user_id == subject_id)
            .where(Notification.type == NotificationType.profile_field_cleared.value)
        )
    ).all()
    # What went, never who took it.
    assert line.data["field"] == "custom_status"
    assert str(moderator.id) not in str(line.data)
