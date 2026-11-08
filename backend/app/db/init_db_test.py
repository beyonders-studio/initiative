"""Tests for first-boot seeding (init_db)."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.encryption import hash_email
from app.db import init_db, schema_provisioning
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.models.platform.guild import Guild
from app.models.platform.user import User
from app.models.platform.user_email import UserEmail
from app.services.platform import guilds as guilds_service


async def test_init_owner_cleans_up_when_guild_seed_fails(engine, monkeypatch):
    """A guild-seed failure during first-boot superuser init must undo the
    already-committed user + guild.

    Otherwise the committed user makes init_owner short-circuit on every
    subsequent restart ("already seeded"), permanently stranding the primary
    guild without a schema. The cleanup mirrors the API/registration paths.
    """
    # init_owner uses SystemSessionLocal (bound to the prod system engine);
    # point it (and provisioning, via the autouse harness) at the test DB.
    test_sessions = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(init_db, "SystemSessionLocal", test_sessions)

    email = "init-boot-seedfail@example.com"
    monkeypatch.setattr(settings, "FIRST_OWNER_EMAIL", email)
    monkeypatch.setattr(settings, "FIRST_OWNER_PASSWORD", "securepassword123")

    async def _boom(seed_session, *, guild_id, **kwargs):
        # Provision and route into the community, then abort the transaction
        # like a real failing query would: the cleanup must roll back and leave
        # the community it removes before it deletes the stranded rows.
        await schema_provisioning.provision_guild(guild_id)
        await set_rls_context(seed_session, SystemGuild(guild_id))
        await seed_session.exec(text("SELECT * FROM does_not_exist_xyz"))

    monkeypatch.setattr(guilds_service, "seed_guild_content", _boom)

    async with test_sessions() as pre:
        guilds_before = len((await pre.exec(select(Guild))).all())

    with pytest.raises(guilds_service.GuildProvisionError):
        await init_db.init_owner()

    async with test_sessions() as check:
        user = (
            await check.exec(
                select(User)
                .join(UserEmail, UserEmail.user_id == User.id)
                .where(UserEmail.email_hash == hash_email(email))
            )
        ).one_or_none()
        assert user is None, (
            "first-boot user must be removed so a restart re-initializes"
        )
        guilds_after = len((await check.exec(select(Guild))).all())
        assert guilds_after == guilds_before, "the primary guild must be removed too"


def test_stamp_this_image_lacks_is_refused_with_instructions():
    """A database stamped ahead of the image stops the boot with a message.

    The message is the whole point: it names the revision the database is at,
    the newest one this image has, and the way back, in place of alembic's
    "Can't locate revision identified by ..." raised from inside the lifespan.
    """
    revisions, head = init_db.migration_chain()
    assert head is not None and head in revisions

    with pytest.raises(SystemExit) as refused:
        init_db._require_image_knows([head, "20991231_9999"])

    said = str(refused.value)
    assert "20991231_9999" in said
    assert head in said
    # The one the image does have is not reported as ahead of it.
    assert said.count(head) == 1


def test_stamp_this_image_has_passes():
    """The ordinary upgrade — every stamped revision is in the chain."""
    revisions, head = init_db.migration_chain()
    assert init_db._require_image_knows([head]) is None
    assert init_db._require_image_knows(sorted(revisions)[:5]) is None


def test_unreadable_chain_is_left_to_alembic(monkeypatch):
    """Nothing to compare against is not evidence the database is ahead."""
    monkeypatch.setattr(init_db, "migration_chain", lambda: (frozenset(), None))
    assert init_db._require_image_knows(["20991231_9999"]) is None


def test_a_failed_start_reports_where_it_stopped_without_secrets(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "p@ss word!")
    revisions, _head = init_db.migration_chain()
    dated = sorted(r for r in revisions if init_db._is_dated_revision(r))
    stamped, stopped = dated[-3], dated[-2]
    error = RuntimeError(
        "could not reach postgresql+asyncpg://owner:pa55word@db/initiative "
        f"with {settings.SECRET_KEY} as p%40ss%20word%21\nthe rest of the traceback"
    )

    report = init_db._failed_start_report(
        error, {"postgres": "17.6", "stamped": stamped}
    )

    assert init_db.get_version() in report
    assert "17.6" in report
    assert f"stopped at:  {stopped}" in report
    assert "pa55word" not in report
    assert settings.SECRET_KEY not in report
    assert "p%40ss%20word%21" not in report
    assert "the rest of the traceback" not in report


async def test_a_failed_start_logs_the_report_and_raises(monkeypatch, caplog):
    async def facts():
        return {"postgres": "17.6", "stamped": "none"}

    async def fail():
        raise RuntimeError("a migration failed")

    async def refuse():
        raise SystemExit("already says what to do")

    monkeypatch.setattr(init_db, "_database_facts", facts)
    monkeypatch.setattr(init_db, "_prepare_database", fail)
    with pytest.raises(RuntimeError, match="a migration failed"):
        await init_db.prepare_database()
    assert "Initiative could not start" in caplog.text

    # A report that cannot be made leaves the error it was about in place.
    def no_report(error, facts):
        raise ValueError("the report broke")

    monkeypatch.setattr(init_db, "_failed_start_report", no_report)
    with pytest.raises(RuntimeError, match="a migration failed"):
        await init_db.prepare_database()

    caplog.clear()
    monkeypatch.setattr(init_db, "_prepare_database", refuse)
    with pytest.raises(SystemExit):
        await init_db.prepare_database()
    assert "Initiative could not start" not in caplog.text


async def test_the_report_reads_the_database(engine):
    facts = await init_db._database_facts()

    assert facts["postgres"][:1].isdigit(), facts
    assert init_db.migration_chain()[1] in facts["stamped"], facts
