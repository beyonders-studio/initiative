from datetime import datetime, timezone
import asyncio
import logging
import re
from urllib.parse import quote, quote_plus

from sqlalchemy import delete as sql_delete
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.security import get_password_hash
from app.core.transitions import TRANSITIONS
from app.core.version import __version__, get_version
from app.db.schema_provisioning import (
    APP_LOGIN_ROLE,
    ensure_shared_table_grants,
    ensure_system_engine_bypassrls,
    verify_engine_identities,
)
from app.db.session import (
    SystemSessionLocal,
    migration_chain,
    migration_lock,
    run_migrations,
)
from app.models.platform.user import User, UserRole
from app.services import audit as audit_service
from app.services.auth import addresses
from app.services.platform import app_settings as app_settings_service
from app.services.platform import dm_settings as dm_settings_service
from app.services.platform import guilds as guilds_service
from app.core import usernames

logger = logging.getLogger(__name__)

# The squashed baseline (v0.53.5 snapshot). Databases stamped at an older
# revision must go through a v0.53.x release first — see check_pre_baseline_db.
BASELINE_REVISION = "20260626_0125"


async def init_owner() -> None:
    if not (settings.FIRST_OWNER_EMAIL and settings.FIRST_OWNER_PASSWORD):
        return

    async with SystemSessionLocal() as session:
        existing = await addresses.find_user_by_address(
            session, settings.FIRST_OWNER_EMAIL
        )
        if existing is not None:
            return  # already seeded

        # Create the first superuser (the platform owner)...
        user = User(
            # Assigned, not picked: the owner chooses one on first sign-in.
            username=usernames.random_name(),
            discriminator=usernames.random_discriminator(),
            hashed_password=get_password_hash(settings.FIRST_OWNER_PASSWORD),
            password_set_at=datetime.now(timezone.utc),
            role=UserRole.owner,
        )
        session.add(user)
        await session.flush()
        addresses.record_address(
            session,
            user_id=user.id,
            email=settings.FIRST_OWNER_EMAIL,
            source=addresses.SOURCE_SIGNUP,
            verified=True,
        )
        await dm_settings_service.seed_for_new_account(session, user_id=user.id)
        # Nobody signed in made this account, so it carries no actor.
        await audit_service.record(
            session,
            event_type=AuditEventType.USER_CREATED,
            actor_user_id=None,
            target_user_id=user.id,
            detail={"via": "bootstrap"},
        )
        await session.commit()

        # ...and their guild the same way the API does. If it cannot be set
        # up, the account goes too: a committed owner makes init_owner return
        # early on every restart, leaving the primary guild without a schema.
        user_id = user.id
        try:
            await guilds_service.provision_new_guild(
                session, name="Primary Community", creator=user
            )
        except guilds_service.GuildProvisionError:
            await session.exec(sql_delete(User).where(User.id == user_id))
            await session.commit()
            raise


def _is_dated_revision(revision: str) -> bool:
    """True for this repo's YYYYMMDD_NNNN revision ids (explicit check)."""
    return (
        len(revision) == 13
        and revision[8] == "_"
        and revision[:8].isdigit()
        and revision[9:].isdigit()
    )


def _require_image_knows(stamped: list[str]) -> None:
    """Exit with instructions if this image lacks a revision the database is
    stamped at — the mirror of the pre-baseline case below, and the same
    cryptic alembic failure ("can't locate revision") if nothing catches it.

    A database gets ahead of its image whenever the container comes back on an
    older one than last upgraded it: a pull that did not replace the tag it was
    meant to, a deliberate roll-back, or a half-finished rebuild whose leftover
    container is the one still being started.
    """
    revisions, head = migration_chain()
    if not revisions:
        return  # Chain unreadable; let alembic surface whatever is wrong with it
    ahead = [revision for revision in stamped if revision not in revisions]
    if not ahead:
        return

    raise SystemExit(
        f"\n{'=' * 70}\n"
        f"This image is older than the database.\n\n"
        f"  database stamped at:   {', '.join(sorted(ahead))}\n"
        f"  newest migration here: {head or '?'}\n"
        f"  this image:            {get_version()}\n\n"
        f"Migrations only run forward, so this version cannot serve this\n"
        f"database. Start the release that last upgraded it — or any newer\n"
        f"one — and the app comes up where it left off.\n\n"
        f"If it keeps coming back on the old image after you pull a new one,\n"
        f"look for a container the upgrade left behind and started instead:\n"
        f"compose renames the one it is replacing to <12 hex characters>_<name>\n"
        f"and leaves it there when the rebuild does not finish. Remove it and\n"
        f"bring the project up again.\n\n"
        f"Running this version deliberately means restoring the database\n"
        f"backup taken before that upgrade; there is no downgrade path.\n"
        f"{'=' * 70}"
    )


async def check_pre_baseline_db(conn: AsyncConnection) -> None:
    """Exit with upgrade instructions if the database predates the v0.53.5
    baseline squash — its revision id no longer exists in this chain, so
    alembic would fail with a cryptic "can't locate revision" otherwise.

    Runs on the migration lock's connection, which autocommits."""
    has_table = await conn.scalar(
        text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables "
            "  WHERE table_schema = 'public' AND table_name = 'alembic_version'"
            ")"
        )
    )
    if not has_table:
        return  # Fresh database

    # Every row, not just one: a database left on a branch carries a stamp
    # per head, and a single image has to be able to run all of them.
    stamped = list(
        (await conn.scalars(text("SELECT version_num FROM alembic_version"))).all()
    )
    if not stamped:
        return  # Fresh database (empty alembic_version)
    revision = stamped[0]

    if revision == BASELINE_REVISION:
        # Stamped at the baseline, but roles may be missing on a database
        # that never actually ran it (e.g. restored without roles). Clear
        # the stamp so the (idempotent) baseline migration re-runs — it
        # recreates roles, RLS policies, and grants as needed.
        has_roles = await conn.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :login)"),
            {"login": APP_LOGIN_ROLE},
        )
        if not has_roles:
            print(
                "Baseline stamped but database roles missing. Re-running baseline migration..."
            )
            await conn.execute(text("DELETE FROM alembic_version"))
        return

    if _is_dated_revision(revision) and revision > BASELINE_REVISION:
        # Post-squash, so alembic can run it — as long as this image is the
        # one that has it. Say so when it isn't, for the same reason the
        # pre-baseline message below exists.
        _require_image_knows(stamped)
        return  # normal upgrade

    raise SystemExit(
        f"\n{'=' * 70}\n"
        f"Pre-v0.53.2 database detected (revision: {revision}).\n\n"
        f"This version's migration history starts at the v0.53.5 baseline;\n"
        f"older databases must step through a v0.53.x release first:\n\n"
        f"  1. Deploy any v0.53.x image (e.g. ghcr.io/beyonders-studio/initiative:0.53.5)\n"
        f"     and let it boot once — its migrations and startup conversion\n"
        f"     bring the database to the baseline state.\n"
        f"  2. Then deploy this version and restart.\n\n"
        f"Step 1 is mandatory, not advisory: it is what copies guild content\n"
        f"into the per-guild schemas. This version DROPS the old copies in\n"
        f"the public schema (migration 20260811_0163) and cannot be rolled\n"
        f"back, so anything not converted by then is lost.\n\n"
        f"(Installs older than v0.30.0 are no longer supported for\n"
        f"in-place upgrade — restore into a fresh install instead.)\n"
        f"{'=' * 70}"
    )


async def migrate_database() -> None:
    """Bring the database to head, one instance at a time.

    The pre-baseline check reads — and on one path clears — the alembic stamp
    that the upgrade then acts on, so the two share a lock rather than taking
    one each.
    """
    async with migration_lock() as conn:
        await check_pre_baseline_db(conn)
        await run_migrations()


#: Where to report a start that failed.
ISSUES_URL = "https://github.com/beyonders-studio/initiative/issues"

_URL_CREDENTIALS = re.compile(r"(://)[^/@\s]+@")

#: Shorter configured values are left alone: taking every two-letter string
#: out of an error would leave nothing to read.
_SHORTEST_SECRET = 4


def _secret_values() -> set[str]:
    """Every configured value a report must not repeat, as written and as a
    URL would encode it: the database passwords, and each setting named as a
    secret, key, token or password."""
    values = set()
    for name, value in settings.model_dump().items():
        if not isinstance(value, str):
            continue
        if name.startswith("DATABASE_URL"):
            try:
                value = make_url(value).password or ""
            except Exception:
                continue
        elif not re.search(r"SECRET|PASSWORD|TOKEN|KEY", name):
            continue
        if len(value) >= _SHORTEST_SECRET:
            values |= {value, quote(value, safe=""), quote_plus(value)}
    return values


def _scrubbed(line: str) -> str:
    line = _URL_CREDENTIALS.sub(r"\1***@", line)
    for value in sorted(_secret_values(), key=len, reverse=True):
        line = line.replace(value, "***")
    return line


async def _database_facts() -> dict[str, str]:
    """The server's version and the revisions the database is stamped at,
    read on the provisioning engine (connected as the app connects), each
    reported as unknown when it cannot be read."""
    from app.db import session as db_session

    facts: dict[str, str] = {}

    async def read() -> None:
        async with db_session.provisioning_engine.connect() as conn:
            facts["postgres"] = str(await conn.scalar(text("SHOW server_version")))
            if await conn.scalar(text("SELECT to_regclass('public.alembic_version')")):
                rows = await conn.execute(
                    text("SELECT version_num FROM alembic_version")
                )
                facts["stamped"] = ", ".join(sorted(r[0] for r in rows)) or "none"
            else:
                facts["stamped"] = "none"

    try:
        await asyncio.wait_for(read(), timeout=10)
    except Exception as error:
        reason = f"unknown ({type(error).__name__})"
        facts.setdefault("postgres", reason)
        facts.setdefault("stamped", reason)
    return facts


def _failed_start_report(error: BaseException, facts: dict[str, str]) -> str:
    """What a start that failed prints, for its operator to paste into an
    issue: the version, how the database is given, the server's version,
    where the migrations stand, and the error's first line, with the
    passwords and keys it is configured with taken out."""
    revisions, head = migration_chain()
    stamped = facts.get("stamped", "unknown")
    lines = [
        ("version", get_version()),
        (
            "database",
            "one DATABASE_URL"
            if settings.database_logins_derived
            else "separate logins",
        ),
        ("postgres", facts.get("postgres", "unknown")),
        ("migrations", f"database at {stamped}, this version at {head or 'unknown'}"),
    ]
    # Revisions are dated, so the one after the stamp is the one a failed
    # upgrade stopped at.
    if _is_dated_revision(stamped) and head and stamped < head:
        after = sorted(r for r in revisions if _is_dated_revision(r) and r > stamped)
        if after:
            lines.append(("stopped at", after[0]))
    message = str(error).strip().splitlines()
    lines.append(
        ("error", f"{type(error).__name__}: {message[0] if message else ''}"[:300])
    )
    body = "\n".join(
        f"  {label + ':':<12} {_scrubbed(value)}" for label, value in lines
    )
    return (
        f"\n{'=' * 70}\n"
        f"Initiative could not start.\n\n"
        f"To report it, open an issue at\n"
        f"  {ISSUES_URL}\n"
        f"and paste this block. The passwords and keys this server is\n"
        f"configured with are taken out; read it over before you post it.\n\n"
        f"{body}\n"
        f"{'=' * 70}"
    )


async def prepare_database() -> None:
    """Bring the database to what this release serves, and seed it.

    Every step is idempotent. The server's startup runs this before it serves
    anything, and ``python -m app.db.init_db`` runs it on its own. A failure
    is logged with a short report to paste into an issue, then raised as it
    was; the refusals that already say what to do (``SystemExit``) pass
    through untouched.
    """
    try:
        await _prepare_database()
    except Exception as error:
        # The report is a courtesy: if it cannot be made, the error it was
        # about is still the one raised.
        try:
            report = _failed_start_report(error, await _database_facts())
        except Exception:
            logger.exception("The report on this failed start could not be made")
        else:
            logger.error(report)
        raise


async def _prepare_database() -> None:
    # The prerequisites the app's own logins cannot create for themselves: the
    # logins, and the guild-search match operator. Applied from
    # DATABASE_URL_BOOTSTRAP when set, verified otherwise, before anything
    # connects as those logins.
    from app.db.bootstrap import ensure_database_bootstrap

    await ensure_database_bootstrap()
    # A deployment that removed DATABASE_URL_BOOTSTRAP (or never set it) has no
    # path that moves object ownership to the provisioning login, and every
    # boot heal below that rewrites a function or a community schema needs it.
    from app.db.bootstrap import warn_if_ownership_was_never_handed_over

    await warn_if_ownership_was_never_handed_over()
    # Before any DDL runs: check the connection is the least-privilege
    # provisioning login. Ahead of the migrations rather than beside the other
    # heals below, so a misconfigured connection is caught before it reshapes
    # the schema.
    from app.db.schema_provisioning import reject_privileged_database_url

    await reject_privileged_database_url()
    await migrate_database()
    # Who may write the request's session variables. After the migrations,
    # which create the shared floors that keep the right to.
    from app.db.bootstrap import ensure_set_config_narrowed

    await ensure_set_config_narrowed()
    # The functions every guild policy defers to, from the module that owns
    # them (app.db.authorization). Before the back-fill below, so a schema
    # rendered in this same boot finds each one its policies name.
    from app.db.authorization import ensure_authorization_functions
    from app.db.public_rls import ensure_public_rls

    await ensure_authorization_functions()
    # Whether plans are billing's, which the plan and status triggers read.
    from app.db.billing_managed import ensure_billing_managed

    await ensure_billing_managed()
    # The shared tables' row security, from its registry (app.db.public_rls),
    # the way the guild schemas get theirs from INITIATIVE_PATHS. Stamped on
    # the public schema, so a boot with nothing changed does nothing.
    await ensure_public_rls()
    # Bring every guild schema up to date: the parts of provisioning whose
    # render changed since a guild was stamped are re-applied, and a guild left
    # without a schema (e.g. a crash mid-provision) gets all of them. One
    # broken guild is logged and skipped; current guilds are not touched.
    from app.db.schema_provisioning import (
        backfill_guild_schemas,
        backfill_guild_search,
        warn_if_search_operator_missing,
    )

    # Before the heals: name the three DB logins in the log, and warn loudly
    # on wiring that collapses the role separation (app/admin URLs sharing a
    # login, a privileged app login) — so the operator sees which login each
    # repair below will act on.
    await verify_engine_identities()
    # Before anything touches the system engine: confirm its login holds
    # BYPASSRLS, which a restored database or a hand-created role can lack and
    # the seeding below needs (issue #835).
    await ensure_system_engine_bypassrls()
    # One gate deeper: a restored/recreated role can bypass RLS yet be missing
    # the per-table GRANTs (cluster state a stamped DB never re-applies), so
    # seeding dies on "permission denied for table guilds" instead. Re-assert
    # the audited shared-table grants from the registry (issue #835 follow-up).
    # It heals the logins the URLs connect as and stops with the exact GRANTs
    # when that does not take.
    await ensure_shared_table_grants()
    await warn_if_search_operator_missing()
    backfill = await backfill_guild_schemas()
    if backfill.failed:
        # WARNING so partial failure survives INFO-filtered logs (per-guild
        # tracebacks were already logged inside the back-fill).
        logger.warning(
            "guild schema back-fill: %d provisioned, %d FAILED (of %d) — guilds %s",
            backfill.provisioned,
            backfill.failed,
            backfill.total,
            backfill.failed_guild_ids,
        )
    else:
        logger.info(
            "guild schema back-fill: %d provisioned, %d up-to-date (of %d)",
            backfill.provisioned,
            backfill.skipped,
            backfill.total,
        )
    # The operations tables and the filer role exist in the operations
    # community alone. Re-asserted after the back-fill, and dropped from any
    # community they were left in.
    from app.db.operations_schema import reconcile_operations

    await reconcile_operations()

    # Every schema the back-fill reached now binds its own copies of the
    # guild functions, so the copies the migrations left in public can go.
    # Postgres refuses each one that a schema still binds (a guild the
    # back-fill skipped); those are logged and tried again next boot.
    from app.db.authorization import ensure_public_copies_dropped

    retired = await ensure_public_copies_dropped()
    if retired.blocked:
        logger.warning(
            "public copies of guild functions still bound, kept for now: %s",
            ", ".join(f"{name} ({count})" for name, count in retired.blocked.items()),
        )
    elif retired.dropped:
        logger.info(
            "public copies of guild functions retired: %s",
            ", ".join(retired.dropped),
        )
    # After the schemas, never before: the sweep writes through functions and
    # into a table whose shape the pass above is what brings up to date.
    await backfill_guild_search()
    # The back-fill opened every stale schema on the provisioning engine; close
    # those connections rather than keep them pooled.
    from app.db import session as db_session

    await db_session.provisioning_engine.dispose()
    # Rotate SECRET_KEY-derived data (encrypted fields + email_hash) when
    # PREVIOUS_SECRET_KEY names a prior key. Runs after guild schemas exist and
    # before traffic is served, so a packaged deploy rotates itself on boot.
    # Idempotent — a no-op once rotated (then unset PREVIOUS_SECRET_KEY).
    from app.db.secret_key_rotation import maybe_rotate_at_startup

    await maybe_rotate_at_startup()
    # Note what this deployment is running, and what it was running before.
    # An announcement meant for people upgrading past some release has no way
    # to know that from a publication date; this pair is how it finds out.
    try:
        async with SystemSessionLocal() as version_session:
            previous = await app_settings_service.record_running_version(
                version_session,
                version=__version__,
                transitions=[transition.name for transition in TRANSITIONS],
                demo_mode=settings.DEMO_MODE,
            )
        if previous and previous != __version__:
            logger.info("upgraded from %s to %s", previous, __version__)
    except Exception:  # pragma: no cover - never hold up boot for bookkeeping
        logger.exception("could not record the running version")
    # First-owner bootstrap (FIRST_OWNER_EMAIL / FIRST_OWNER_PASSWORD): create
    # the owner and their guild on first boot so a self-hosted instance is
    # usable straight from `docker run` with two env vars.
    # No-op when the env vars are unset (the /auth/bootstrap first-user
    # flow still applies) or the owner already exists.)
    try:
        await init_owner()
    except IntegrityError:
        # Unique violation on the owner's address: a concurrent replica won
        # the first-boot race and created the owner between our existence check
        # and commit.
        logger.info("first-owner bootstrap: created by a concurrent replica")
    async with SystemSessionLocal() as session:
        await app_settings_service.ensure_defaults(session)
    # First-boot seed: create the platform OIDC provider row from OIDC_* env
    # values (issuer + client id required; no-op once the row exists — after
    # that the settings UI owns it). Runs on the system engine because the
    # provider registry carries no request-path grants.
    from app.services.auth.platform_provider import seed_platform_provider_from_env

    try:
        async with SystemSessionLocal() as seed_session:
            await seed_platform_provider_from_env(seed_session)
    except Exception:
        logger.exception("Platform OIDC env seed failed; configure via settings UI")

    # The marketplace listings this build ships with. Idempotent upsert on the
    # system engine — the catalog has no request-path writer — so every install
    # has a working marketplace with no network and no configuration.
    from app.services.marketplace.builtin import seed_builtin_listings

    try:
        async with SystemSessionLocal() as catalog_session:
            seeded = await seed_builtin_listings(catalog_session)
            await catalog_session.commit()
        logger.info("marketplace: %d built-in listing(s) seeded", seeded)
    except Exception:
        # A catalog that failed to seed costs the marketplace, not the boot:
        # every already-installed dashboard keeps its own pinned definition.
        logger.exception("marketplace: built-in listing seed failed")

    # Listings the operator publishes themselves, from the directory
    # MARKETPLACE_EXTRA_CATALOG_DIR names. Same writer, same validation as the
    # built-ins; a manifest that has been removed retires its listing. With the
    # setting unset nothing is read, and any operator listing left from a
    # directory that used to be set is withdrawn (the scan logs that itself).
    from app.services.marketplace.operator_catalog import scan_operator_catalog

    try:
        async with SystemSessionLocal() as operator_catalog_session:
            scan = await scan_operator_catalog(operator_catalog_session)
            await operator_catalog_session.commit()
        if scan.configured:
            logger.info(
                "marketplace: operator catalog — %d published, %d withdrawn, "
                "%d skipped",
                scan.published,
                scan.withdrawn,
                scan.skipped,
            )
    except Exception:
        logger.exception("marketplace: operator catalog scan failed")
    # This project's own plug-in publisher. Added once; a row that exists is left
    # exactly as it is, so an operator's switch survives a restart.
    try:
        from app.services.marketplace import publishers as plugin_publishers

        async with SystemSessionLocal() as publisher_session:
            if await plugin_publishers.seed_publishers(publisher_session):
                logger.info("plug-in publishers: seeded this project's publisher")
    except Exception:
        logger.exception("plug-in publishers: seeding failed")
    # Plug-in services the deployment declares in a mounted file (PLUGIN_SERVICES_CONFIG).
    # Database-only: a plug-in's container may boot after this one, and nothing is
    # fetched from it. No-op when the setting is unset.
    if settings.PLUGIN_SERVICES_CONFIG:
        try:
            from app.services.marketplace import registrations as plugin_registrations

            async with SystemSessionLocal() as plugin_service_session:
                reconciled = await plugin_registrations.reconcile_from_config(
                    plugin_service_session
                )
            logger.info(
                "plug-in services: %d updated, %d unchanged, %d waiting for their "
                "listing, %d skipped",
                reconciled.updated,
                reconciled.unchanged,
                reconciled.waiting,
                reconciled.skipped,
            )
        except Exception:
            # A registration that failed to reconcile costs that plug-in, not the
            # boot; already-stored registrations keep working unchanged.
            logger.exception("plug-in services: reconciliation from config failed")

    # Plug-ins the deployment provides to every guild (§7.7). New guilds get theirs
    # at creation; this is how the flag reaches guilds that predate it, on the
    # same sweep pattern that reprovisions stale schemas. Returns immediately
    # when nothing is marked mandatory, which is every install that has not
    # asked for this.
    try:
        from app.services.tenant import mandatory_plugins as mandatory_plugins_service

        backfilled = await mandatory_plugins_service.backfill_mandatory_plugins()
        if backfilled.installed or backfilled.failed:
            logger.info(
                "mandatory plug-ins: %d installed across %d guild(s), %d failed",
                backfilled.installed,
                backfilled.guilds,
                backfilled.failed,
            )
    except Exception:
        # A guild missing a mandatory plug-in is a gap the next boot closes; it is
        # not a reason to refuse to start.
        logger.exception("mandatory plug-ins: backfill failed")


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(prepare_database())
