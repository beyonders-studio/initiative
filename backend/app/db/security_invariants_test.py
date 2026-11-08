"""The database privilege posture, asserted as CI invariants.

The actor model is only
as durable as the catalog state that implements it — a hotfix migration adding
a broad ``GRANT``, a manually flipped role attribute, or a new RLS table
without a decision would all land silently. These tests re-derive the posture
from the live catalog on every run, the same way ``tenancy_test`` enforces
table placement:

* the app's role families never hold SUPERUSER; ``app_admin`` is the ONLY
  BYPASSRLS holder (PostgreSQL's trusted-batch actor, grant-bounded);
* ``app_admin`` (and ``app_user``) per-table grants equal the audited registry
  in ``app.db.system_grants`` — new shared tables give the system engine (and
  the bare login role) nothing until the registry (and a migration) says so;
* each ``platform_<tier>`` role's direct table grants equal the tier registry
  rendered through the capabilities;
* every RLS-enabled shared table is FORCEd (even table owners obey policies);
* the retired ``is_superadmin`` GUC appears in no policy anywhere;
* no app role may CREATE objects in ``public`` (it is on every search_path);
* login-role memberships in scoped roles are INHERIT FALSE (no standing
  access without an explicit ``SET ROLE``).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.models.platform.user import UserRole
from app.db.user_columns import PUBLIC_PROFILE_COLUMNS, PUBLISHED_COLUMNS
from app.db.public_rls import PUBLIC_RLS, platform_tier, role_name
from app.db.system_grants import ROLE_GRANTS, grantee, tier_table_grants

pytestmark = pytest.mark.always


# Shared tables that carry (FORCEd) row-level security: what the registry in
# app.db.public_rls says is on. The catalog is the other side of the check.
_RLS_SHARED_TABLES = {t for t, rls in PUBLIC_RLS.items() if rls.enabled}


@pytest.fixture(autouse=True)
async def _materialize_lazy_shared_tables():
    """``storage_backfill_state`` is created lazily at runtime, not by a
    migration — without this the catalog assertions below would depend on
    whether a storage test happened to run first. Creating it here also
    converges a table left behind by an earlier build on the current grant
    set (the create path is revoke-then-grant, idempotent)."""
    from app.services.storage_backfill import _ensure_table

    await _ensure_table()


def _app_role_family() -> list[str]:
    """The fixed app roles plus this worker's prefixed platform ladder."""
    return [
        "app_user",
        "app_admin",
        "app_guild_base",
        role_name("platform_base"),
        "app_superadmin",
        "plugin_install_base",
        *(role_name(platform_tier(t)) for t in UserRole),
        role_name("initiative_billing"),
    ]


async def test_no_app_role_is_superuser_and_only_app_admin_bypasses_rls(engine):
    roles = _app_role_family()
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = ANY(:r)"
                ),
                {"r": roles},
            )
        ).all()
    found = {r[0]: (r[1], r[2]) for r in rows}
    assert "app_user" in found and "app_admin" in found, "login roles must exist"
    for name, (is_super, bypass) in found.items():
        assert not is_super, f"{name} must never be SUPERUSER"
        if name == "app_admin":
            assert bypass, (
                "app_admin is the designated trusted-batch actor (BYPASSRLS, "
                "bounded by enumerated grants)"
            )
        else:
            assert not bypass, f"{name} must not carry BYPASSRLS"


async def _table_grants_for(engine, role: str) -> dict[str, set[str]]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT c.relname, a.privilege_type FROM pg_class c, "
                    "LATERAL aclexplode(c.relacl) a "
                    "WHERE c.relnamespace = 'public'::regnamespace "
                    "AND c.relkind = 'r' "
                    "AND a.grantee = CAST(:role AS regrole)"
                ),
                {"role": role},
            )
        ).all()
    live: dict[str, set[str]] = {}
    for table, verb in rows:
        live.setdefault(table, set()).add(verb)
    return live


def _assert_matrix(role: str, live: dict[str, set[str]], matrix) -> None:
    for table, expected in matrix.items():
        got = live.pop(table, set())
        assert got == (expected or set()), (
            f"{role} grants drifted on {table!r}: expected "
            f"{sorted(expected or set())}, catalog has {sorted(got)}"
        )
    assert live == {}, (
        f"shared tables with {role} grants but no decision in the "
        f"app/db/public_rls.py registry (add it to the table's Grants, and have the "
        f"migration's GRANT/REVOKE match it): {sorted(live)}"
    )


@pytest.mark.parametrize("role", sorted(ROLE_GRANTS))
async def test_role_grants_match_the_registry(engine, role):
    """Each role's reach into ``public`` is what the registry says.

    The guild and platform floors are granted by the schema default rather
    than table by table, so for them this is the check that a shared table
    added later has had its reach decided (a ``REVOKE`` in the migration where
    the registry says ``None``) instead of inherited. The seat and install
    floors take no default privileges, so anything they hold that the registry
    does not name arrived by a hand-written grant."""
    live = await _table_grants_for(engine, grantee(role))
    _assert_matrix(role, live, ROLE_GRANTS[role])


async def test_platform_tier_grants_match_the_tier_registry(engine):
    """Each tier holds, of its own, what the tier registry renders and nothing
    more.

    Only the grants naming the tier role itself are read: what it inherits
    from ``platform_base`` is the platform floor's matrix, checked above. A
    tier the registry gives nothing holds no table grant at all."""
    for tier, tables in sorted(tier_table_grants().items()):
        role = role_name(tier)
        live = await _table_grants_for(engine, role)
        _assert_matrix(role, live, tables)


async def test_the_guild_floor_does_not_delete_a_community(engine):
    """A community is created, deleted and purged on the system engine; the
    guild floor reads it and writes only the columns its admin edits."""
    async with engine.connect() as conn:
        for role in ("app_guild_base", "app_guild_base_ro"):
            for verb in ("INSERT", "DELETE"):
                held = await conn.scalar(
                    text("SELECT has_table_privilege(:role, 'public.guilds', :verb)"),
                    {"role": role, "verb": verb},
                )
                assert not held, f"{role} must not hold {verb} on guilds"


async def test_an_invite_is_reached_only_from_its_community(engine):
    """The platform floor and the bare login hold nothing on ``guild_invites``,
    and the guild floor holds no UPDATE. Its policies name the guild floors
    alone."""
    async with engine.connect() as conn:
        for role in (role_name("platform_base"), "app_user"):
            for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                held = await conn.scalar(
                    text(
                        "SELECT has_table_privilege(:role,"
                        " 'public.guild_invites', :verb)"
                    ),
                    {"role": role, "verb": verb},
                )
                assert not held, f"{role} must not hold {verb} on guild_invites"
        held = await conn.scalar(
            text(
                "SELECT has_table_privilege('app_guild_base',"
                " 'public.guild_invites', 'UPDATE')"
            )
        )
        assert not held, "app_guild_base must not hold UPDATE on guild_invites"
        roles = {
            tuple(sorted(row[0]))
            for row in (
                await conn.execute(
                    text(
                        "SELECT roles FROM pg_policies WHERE schemaname = 'public'"
                        " AND tablename = 'guild_invites'"
                    )
                )
            ).all()
        }
    assert roles <= {("app_guild_base",), ("app_guild_base", "app_guild_base_ro")}, (
        f"guild_invites policies name roles beyond the guild floors: {roles}"
    )


async def test_the_seat_floor_alone_writes_the_sign_in_rule(engine):
    """Setting how a community signs its members in is the seat's.

    Every floor reads the rule — the gate function runs under whichever role
    the request assumed — and only the floor a seat route inherits writes it."""
    async with engine.connect() as conn:
        for role in (
            "app_guild_base",
            role_name("platform_base"),
            "app_user",
        ):
            for verb in ("INSERT", "UPDATE", "DELETE"):
                held = await conn.scalar(
                    text(
                        "SELECT has_table_privilege(:role,"
                        " 'public.community_rules', :verb)"
                    ),
                    {"role": role, "verb": verb},
                )
                assert not held, f"{role} must not hold {verb} on community_rules"
        for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            held = await conn.scalar(
                text(
                    "SELECT has_table_privilege('app_superadmin',"
                    " 'public.community_rules', :verb)"
                ),
                {"verb": verb},
            )
            assert held, f"app_superadmin must hold {verb} on community_rules"


async def test_the_seat_writes_its_rules_and_nothing_of_the_guild_row(engine):
    """The seat changes what its community asks of the people reaching it, and
    nothing else about the community: it writes ``community_rules`` and no
    column of ``guilds``. A name, an icon, an owner or a lifecycle status is
    not the seat's, and a new column on ``guilds`` is not either until a
    migration says so.
    """
    async with engine.connect() as conn:
        writable = (
            await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_schema = 'public' AND table_name = 'guilds'"
                    " AND has_column_privilege("
                    "'app_superadmin', 'public.guilds', column_name, 'UPDATE')"
                )
            )
        ).all()
        assert writable == [], f"the seat floor writes guilds columns: {writable}"
        for verb in ("INSERT", "UPDATE", "DELETE"):
            held = await conn.scalar(
                text("SELECT has_table_privilege('app_superadmin', :t, :v)"),
                {"t": "public.guilds", "v": verb},
            )
            assert not held, f"the seat floor must not hold {verb} on guilds"
            held = await conn.scalar(
                text("SELECT has_table_privilege('app_superadmin', :t, :v)"),
                {"t": "public.community_rules", "v": verb},
            )
            assert held, f"the seat floor must hold {verb} on community_rules"


async def test_guild_image_bytes_are_unreadable_by_request_roles(engine):
    """A request-path role may name a guild image but never read one.

    The guild list carries an icon's and a banner's URL, which needs their
    digests — a membership fact, granted column by column. The bytes are not in
    that grant: they are served by one endpoint on the system engine, which is
    where the rule about who may see a stranger's icon or card rendition lives.
    A new column on ``guild_images`` is unreadable to the request path until a
    migration says otherwise, which is the point.
    """
    request_roles = [
        "app_guild_base",
        role_name("platform_base"),
        "app_user",
    ]
    readable = {"guild_id", "variant", "sha256"}
    async with engine.connect() as conn:
        for role in request_roles:
            rows = (
                await conn.execute(
                    text(
                        "SELECT column_name, "
                        "has_column_privilege(:role, 'public.guild_images', "
                        "column_name, 'SELECT') AS can_read "
                        "FROM information_schema.columns "
                        "WHERE table_schema = 'public' "
                        "AND table_name = 'guild_images'"
                    ),
                    {"role": role},
                )
            ).all()
            assert rows, "guild_images must exist"
            got = {column for column, can_read in rows if can_read}
            assert got == readable, (
                f"{role} may read {sorted(got)} of guild_images; expected "
                f"exactly {sorted(readable)}"
            )


async def test_profile_view_publishes_only_the_public_columns(engine):
    """What is public about an account is decided in the catalog.

    ``public.user_profiles`` is the projection the profile endpoint reads, and
    it is not a convention the handler keeps: the reader role behind the view
    holds SELECT on exactly the public columns of ``public.users``, so a column
    added to the view without a matching grant returns nothing, and one added
    to the table is not in the view until somebody puts it there (migration
    0214)."""
    public_columns = set(PUBLIC_PROFILE_COLUMNS)
    base = role_name("platform_base")
    async with engine.connect() as conn:
        view_columns = {
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' "
                        "AND table_name = 'user_profiles'"
                    )
                )
            ).all()
        }
        assert view_columns == public_columns, (
            "public.user_profiles carries columns that were not decided as "
            f"public: {sorted(view_columns - public_columns)}; missing "
            f"{sorted(public_columns - view_columns)}"
        )

        readable = {
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT column_name, has_column_privilege("
                        "'app_profile_reader', 'public.users', column_name, "
                        "'SELECT') FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'users'"
                    )
                )
            ).all()
            if row[1]
        }
        # The reader owns both projections, and both read the profile's
        # columns of the account and nothing more.
        expected = set(PUBLISHED_COLUMNS)
        assert readable == expected, (
            "app_profile_reader reads columns of public.users that are not "
            f"published: {sorted(readable - expected)}; missing "
            f"{sorted(expected - readable)}"
        )

        # Neither projection reads anything off the guild, so the reader holds
        # no column of ``guilds`` and no verb on it.
        guild_readable = {
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT column_name, has_column_privilege("
                        "'app_profile_reader', 'public.guilds', column_name, "
                        "'SELECT') FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'guilds'"
                    )
                )
            ).all()
            if row[1]
        }
        assert not guild_readable, (
            "app_profile_reader reads columns of public.guilds: "
            f"{sorted(guild_readable)}"
        )
        for verb in ("INSERT", "UPDATE", "DELETE"):
            can_write = (
                await conn.execute(
                    text(
                        "SELECT has_table_privilege('app_profile_reader', "
                        f"'public.guilds', '{verb}')"
                    )
                )
            ).scalar()
            assert not can_write, f"app_profile_reader must not hold {verb} on guilds"

        # It reads, and that is all it does — to the table or to the view.
        for verb in ("INSERT", "UPDATE", "DELETE"):
            can_write = (
                await conn.execute(
                    text(
                        "SELECT has_table_privilege('app_profile_reader', "
                        f"'public.users', '{verb}')"
                    )
                )
            ).scalar()
            assert not can_write, f"app_profile_reader must not hold {verb}"

        # The request path reads the view and cannot write through it — the
        # schema's default privileges would otherwise have granted all four.
        can_read = (
            await conn.execute(
                text(
                    "SELECT has_table_privilege(:role, 'public.user_profiles', "
                    "'SELECT')"
                ),
                {"role": base},
            )
        ).scalar()
        assert can_read, f"{base} must be able to read public.user_profiles"
        for verb in ("INSERT", "UPDATE", "DELETE"):
            can_write = (
                await conn.execute(
                    text(
                        "SELECT has_table_privilege(:role, "
                        f"'public.user_profiles', '{verb}')"
                    ),
                    {"role": base},
                )
            ).scalar()
            assert not can_write, f"{base} must not hold {verb} on public.user_profiles"

        # And it holds no standing bypass of its own.
        bypasses = (
            await conn.execute(
                text(
                    "SELECT rolbypassrls FROM pg_roles "
                    "WHERE rolname = 'app_profile_reader'"
                )
            )
        ).scalar()
        assert not bypasses, "app_profile_reader must not hold BYPASSRLS"


#: ``users`` columns written only through capability-gated endpoints on the
#: system engine: the platform-tier ladder, and why an account was suspended.
SYSTEM_ONLY_USER_COLUMNS = {"role", "status_reason"}


async def test_users_role_is_writable_only_by_the_system_engine(engine):
    """``users.role`` (the platform-tier ladder) and ``users.status_reason`` are
    written only through capability-gated endpoints that run on the system
    engine. Each request-path floor holds a column-scoped UPDATE covering every
    other ``users`` column; ``app_admin`` keeps the full grant the endpoints
    rely on (migrations 0144, 20261001_0429). A new ``users`` column must be granted to the request
    floors too, or this test fails — the same "decide it explicitly" discipline
    as the table-grant registry."""
    # ``app_guild_base`` is absent: the guild-routed path holds nothing on the
    # table at all (0221), which
    # ``test_the_guild_path_holds_nothing_on_the_users_table`` asserts instead.
    request_roles = [
        role_name("platform_base"),
        "app_user",
    ]
    async with engine.connect() as conn:
        all_columns = set(
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'users'"
                    )
                )
            ).scalars()
        )
        expected = all_columns - SYSTEM_ONLY_USER_COLUMNS
        for role in request_roles:
            rows = (
                await conn.execute(
                    text(
                        "SELECT column_name, "
                        "has_column_privilege(:role, 'public.users', column_name, "
                        "'UPDATE') AS can_update "
                        "FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'users'"
                    ),
                    {"role": role},
                )
            ).all()
            writable = {name for name, can_update in rows if can_update}
            assert not writable & SYSTEM_ONLY_USER_COLUMNS, (
                f"{role} must not hold UPDATE on {sorted(SYSTEM_ONLY_USER_COLUMNS)}"
                " — they are system-engine-only"
            )
            assert writable == expected, (
                f"{role} UPDATE columns on users drifted from 'every column but "
                f"the system-only ones': missing {sorted(expected - writable)}, unexpected "
                f"{sorted(writable - expected)} (grant the new column, or exclude it)"
            )
        # Positive control: the system engine retains the role write its
        # sanctioned endpoint needs.
        admin_can = (
            await conn.execute(
                text(
                    "SELECT has_column_privilege('app_admin', 'public.users', "
                    "'role', 'UPDATE')"
                )
            )
        ).scalar()
        assert admin_can, "app_admin must retain UPDATE on users.role"


async def test_users_request_path_insert_is_pinned_to_member(engine):
    """A request-path insert into ``users`` may only create a plain member; the
    RESTRICTIVE policy from migration 0144 enforces it (``app_admin`` bypasses
    RLS and still seeds the bootstrap owner)."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT permissive, cmd, with_check FROM pg_policies "
                    "WHERE schemaname = 'public' AND tablename = 'users' "
                    "AND policyname = 'users_request_insert_member_only'"
                )
            )
        ).one_or_none()
    assert row is not None, "member-only insert policy on users is missing"
    permissive, cmd, with_check = row
    assert permissive == "RESTRICTIVE", "insert-member policy must be RESTRICTIVE"
    assert cmd == "INSERT"
    assert "role" in (with_check or "") and "member" in (with_check or ""), (
        f"insert-member policy check does not pin role to member: {with_check!r}"
    )


async def test_guild_billing_columns_are_not_writable_by_request_roles(engine):
    """The operator-set fields are not writable by the request-path floors.

    They live in two places: the lifecycle ``status`` pair stayed on ``guilds``
    (every request reads it), and the caps / plan label / sign-in entitlement
    moved to ``guild_administration`` (migration 0178). Neither floor may write
    either — ``guilds`` by column-scoped grant (0138), ``guild_administration``
    by holding no write verb on the table at all. Drift guard."""
    request_roles = ["app_guild_base", role_name("platform_base")]
    async with engine.connect() as conn:
        for role in request_roles:
            writable = {
                column
                for column in ("status", "status_changed_at")
                if (
                    await conn.execute(
                        text(
                            "SELECT has_column_privilege("
                            ":role, 'public.guilds', :column, 'UPDATE')"
                        ),
                        {"role": role, "column": column},
                    )
                ).scalar()
            }
            assert writable == set(), (
                f"{role} must hold no UPDATE on the guilds lifecycle columns — a "
                f"status change is operator/billing-only: {sorted(writable)}"
            )
            # The whole administration table is read-only to the request path,
            # so this is a table-level check rather than a column allowlist.
            granted = {
                verb
                for verb in ("INSERT", "UPDATE", "DELETE")
                if (
                    await conn.execute(
                        text(
                            "SELECT has_table_privilege("
                            ":role, 'public.guild_administration', :verb)"
                        ),
                        {"role": role, "verb": verb},
                    )
                ).scalar()
            }
            assert granted == set(), (
                f"{role} must hold no write verb on guild_administration — caps, "
                f"plan label, and sign-in entitlement are operator-set: "
                f"{sorted(granted)}"
            )
        # Positive controls, so the assertions above can't pass on a blanket revoke.
        identity_writable = (
            await conn.execute(
                text(
                    "SELECT has_column_privilege("
                    "'app_guild_base', 'public.guilds', 'name', 'UPDATE')"
                )
            )
        ).scalar()
        assert identity_writable, (
            "app_guild_base must retain UPDATE on guilds.name (guild identity)"
        )
        caps_readable = (
            await conn.execute(
                text(
                    "SELECT has_table_privilege("
                    "'app_guild_base', 'public.guild_administration', 'SELECT')"
                )
            )
        ).scalar()
        assert caps_readable, (
            "app_guild_base must retain SELECT on guild_administration — a guild "
            "admin's settings page shows usage against the caps"
        )


async def test_guild_membership_role_is_writable_only_by_the_system_engine(engine):
    """``position`` and ``display_name`` are the membership columns a request
    writes.

    A guild membership's ``role`` is changed on the system engine (the
    guild-admin endpoint), as is the OIDC flag; ``guild_id``, ``user_id`` and
    ``joined_at`` are set once, when the row is created. That leaves the guild
    list's own order, which both request-path floors hold a column-scoped
    UPDATE of — enough for the ``SELECT ... FOR UPDATE`` row locks the
    self-leave and last-admin checks take — and the name a member gives
    themselves in a community, which only the routed guild floor writes.
    ``app_admin`` keeps the full grant (migrations 0145, 0266, 0438)."""
    request_roles = {
        "app_guild_base": {"position", "display_name"},
        role_name("platform_base"): {"position"},
    }
    async with engine.connect() as conn:
        for role, expected in request_roles.items():
            rows = (
                await conn.execute(
                    text(
                        "SELECT column_name, has_column_privilege("
                        ":role, 'public.guild_memberships', column_name, 'UPDATE') "
                        "AS can_update FROM information_schema.columns "
                        "WHERE table_schema = 'public' "
                        "AND table_name = 'guild_memberships'"
                    ),
                    {"role": role},
                )
            ).all()
            writable = {name for name, can_update in rows if can_update}
            assert "role" not in writable, (
                f"{role} must not hold UPDATE on guild_memberships.role — a guild "
                "role change is system-engine-only"
            )
            assert writable == expected, (
                f"{role} UPDATE columns on guild_memberships drifted: missing {sorted(expected - writable)}, "
                f"unexpected {sorted(writable - expected)}"
            )
        admin_can = (
            await conn.execute(
                text(
                    "SELECT has_column_privilege('app_admin', "
                    "'public.guild_memberships', 'role', 'UPDATE')"
                )
            )
        ).scalar()
        assert admin_can, "app_admin must retain UPDATE on guild_memberships.role"


async def test_guild_membership_write_policies_are_tightened(engine):
    """Every request-path membership write is scoped to the caller's own row.

    Self-leave DELETE and the reorder UPDATE both match on
    ``app.current_user_id`` (migrations 0145, 0266). Joining is the system
    engine's (0354): no request-path role holds INSERT and no policy admits
    one. The UPDATE matching the caller rather than the routed guild is what
    lets the guild list be reordered from the platform path, which carries no
    guild at all."""
    async with engine.connect() as conn:
        policies = {
            name: (permissive, cmd, qual, with_check)
            for name, permissive, cmd, qual, with_check in (
                await conn.execute(
                    text(
                        "SELECT policyname, permissive, cmd, qual, with_check "
                        "FROM pg_policies WHERE schemaname = 'public' "
                        "AND tablename = 'guild_memberships'"
                    )
                )
            ).all()
        }
    delete_policy = policies.get("guild_memberships_delete")
    assert delete_policy is not None, "guild_memberships_delete policy is missing"
    assert "current_user_id" in (delete_policy[2] or ""), (
        f"delete policy must scope to the caller's own row: {delete_policy[2]!r}"
    )
    update_policy = policies.get("guild_memberships_update")
    assert update_policy is not None, "guild_memberships_update policy is missing"
    assert "current_user_id" in (update_policy[2] or ""), (
        f"update policy must scope to the caller's own row: {update_policy[2]!r}"
    )
    assert "current_user_id" in (update_policy[3] or ""), (
        f"update policy must check the caller's own row: {update_policy[3]!r}"
    )
    assert "current_guild_id" not in (update_policy[2] or ""), (
        "update policy must not require a routed guild — the guild list is "
        f"reordered with none: {update_policy[2]!r}"
    )
    inserting = sorted(
        name for name, (_, cmd, _, _) in policies.items() if cmd == "INSERT"
    )
    assert inserting == [], f"no policy admits a request-path join: {inserting}"
    async with engine.connect() as conn:
        for role in (
            "app_guild_base",
            role_name("platform_base"),
            "app_user",
        ):
            held = await conn.scalar(
                text(
                    "SELECT has_table_privilege(:role,"
                    " 'public.guild_memberships', 'INSERT')"
                ),
                {"role": role},
            )
            assert not held, f"{role} must not hold INSERT on guild_memberships"


async def test_access_grants_are_writable_only_by_the_system_engine(engine):
    """Access grants are written only on the system engine (the capability-gated
    endpoints). The request-path floors keep SELECT (a grantee reads their own
    live grant) but hold no INSERT/UPDATE/DELETE; ``app_admin`` keeps the full
    grant (migration 0146)."""
    request_roles = ["app_guild_base", role_name("platform_base")]
    async with engine.connect() as conn:
        for role in request_roles:
            select_, insert_, update_, delete_ = (
                await conn.execute(
                    text(
                        "SELECT "
                        "has_table_privilege(:r, 'public.access_grants', 'SELECT'), "
                        "has_table_privilege(:r, 'public.access_grants', 'INSERT'), "
                        "has_table_privilege(:r, 'public.access_grants', 'UPDATE'), "
                        "has_table_privilege(:r, 'public.access_grants', 'DELETE')"
                    ),
                    {"r": role},
                )
            ).one()
            assert select_, f"{role} should keep SELECT on access_grants"
            assert not (insert_ or update_ or delete_), (
                f"{role} must not write access_grants — grants are "
                f"system-engine-only (INSERT={insert_} UPDATE={update_} "
                f"DELETE={delete_})"
            )
        admin_writes = (
            await conn.execute(
                text(
                    "SELECT has_table_privilege('app_admin', "
                    "'public.access_grants', 'INSERT')"
                )
            )
        ).scalar()
        assert admin_writes, "app_admin must retain write on access_grants"


async def test_rls_shared_tables_are_forced(engine):
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relnamespace = 'public'::regnamespace "
                    "AND relkind = 'r'"
                )
            )
        ).all()
    rls_tables = {r[0] for r in rows if r[1]}
    assert rls_tables == _RLS_SHARED_TABLES, (
        "the set of RLS-enabled shared tables changed — decide FORCE + policies "
        f"+ update this invariant. Diff: +{sorted(rls_tables - _RLS_SHARED_TABLES)} "
        f"-{sorted(_RLS_SHARED_TABLES - rls_tables)}"
    )
    not_forced = {r[0] for r in rows if r[1] and not r[2]}
    assert not_forced == set(), (
        f"RLS tables must be FORCEd (owners obey policies too): {sorted(not_forced)}"
    )


async def test_no_policy_references_retired_superadmin_guc(engine):
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT schemaname, tablename, policyname FROM pg_policies "
                    "WHERE COALESCE(qual, '') LIKE '%is_superadmin%' "
                    "OR COALESCE(with_check, '') LIKE '%is_superadmin%'"
                )
            )
        ).all()
    assert rows == [], f"policies still reference the retired GUC: {rows}"


async def test_no_app_role_can_create_in_public(engine):
    """A role that can CREATE in ``public`` could shadow the shared,
    unqualified-name trigger functions/types via search_path — only the
    provisioning (owner) role may define objects."""
    async with engine.connect() as conn:
        for role in _app_role_family():
            can_create = (
                await conn.execute(
                    text("SELECT has_schema_privilege(:r, 'public', 'CREATE')"),
                    {"r": role},
                )
            ).scalar()
            assert not can_create, f"{role} must not CREATE in public"


async def test_login_role_memberships_in_scoped_roles_are_inherit_false(engine):
    """The login roles may only reach scoped (guild/platform) roles via an
    explicit ``SET ROLE`` — a standing (INHERIT) membership would grant every
    request ambient access to every guild."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT m.rolname AS member, r.rolname AS granted, "
                    "am.inherit_option "
                    "FROM pg_auth_members am "
                    "JOIN pg_roles m ON m.oid = am.member "
                    "JOIN pg_roles r ON r.oid = am.roleid "
                    "WHERE m.rolname IN ('app_user', 'app_admin') "
                    "AND (r.rolname LIKE '%guild\\_%' OR r.rolname LIKE '%platform\\_%' "
                    "OR r.rolname LIKE '%initiative\\_billing')"
                )
            )
        ).all()
    inheriting = [(m, g) for m, g, inh in rows if inh]
    assert inheriting == [], (
        f"login-role memberships must be INHERIT FALSE (SET ROLE only): {inheriting}"
    )


async def test_no_default_privileges_for_login_roles(engine):
    """New shared tables must grant the login roles nothing until a migration
    decides (0129/0130 revoked the blanket future-table grants). Routed access
    for new tables comes via platform_base / app_guild_base, whose defaults
    are deliberately kept."""
    async with engine.connect() as conn:
        hits = (
            await conn.execute(
                text(
                    "SELECT r.rolname, d.defaclobjtype, a.privilege_type "
                    "FROM pg_default_acl d, LATERAL aclexplode(d.defaclacl) a "
                    "JOIN pg_roles r ON r.oid = a.grantee "
                    "WHERE d.defaclnamespace = 'public'::regnamespace "
                    "AND r.rolname IN ('app_admin', 'app_user')"
                )
            )
        ).all()
    assert hits == [], (
        f"default privileges silently grant future objects to login roles: {hits}"
    )


async def test_the_guild_path_holds_nothing_on_the_users_table(engine):
    """A guild-routed session cannot name ``public.users``.

    ``app_guild_base`` is what every ``guild_<id>`` and ``guild_<id>_ro`` role
    inherits its shared-table access from, so this one role is the whole guild
    path. It holds no table privilege and no column privilege: the projection
    it reads is ``public.guild_member_profiles`` (0220), and the table went
    with 0221.

    Asserted per column as well as per table, because the two are granted
    separately and a column grant outlives a table-level revoke. This is also
    what makes a column added to ``users`` private by construction — there is
    no grant to forget to narrow.
    """
    async with engine.connect() as conn:
        for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            held = (
                await conn.execute(
                    text(
                        "SELECT has_table_privilege('app_guild_base', "
                        f"'public.users', '{verb}')"
                    )
                )
            ).scalar()
            assert not held, f"app_guild_base must not hold {verb} on public.users"

        for verb in ("SELECT", "INSERT", "UPDATE"):
            reachable = {
                row[0]
                for row in (
                    await conn.execute(
                        text(
                            "SELECT column_name, has_column_privilege("
                            "'app_guild_base', 'public.users', column_name, "
                            f"'{verb}') FROM information_schema.columns "
                            "WHERE table_schema = 'public' AND table_name = 'users'"
                        )
                    )
                ).all()
                if row[1]
            }
            assert not reachable, (
                f"app_guild_base holds {verb} on users columns "
                f"{sorted(reachable)} — the guild path reads "
                "public.guild_member_profiles instead"
            )


async def test_guild_member_view_publishes_the_guild_projection(engine):
    """What a guild-routed session may read of a person is a catalog fact.

    ``public.guild_member_profiles`` carries the profile's columns plus
    ``display_name``, and the guild path and a guest hold SELECT on the view and nothing
    else — the schema's default privileges would otherwise have granted all
    four verbs (migration 0220).
    """
    expected = set(PUBLIC_PROFILE_COLUMNS) | {"display_name"}
    base = role_name("platform_base")
    async with engine.connect() as conn:
        view_columns = {
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' "
                        "AND table_name = 'guild_member_profiles'"
                    )
                )
            ).all()
        }
        assert view_columns == expected, (
            "public.guild_member_profiles carries columns that were not "
            f"decided: {sorted(view_columns - expected)}; missing "
            f"{sorted(expected - view_columns)}"
        )

        # The guild floor and the guest floor read it; neither writes it.
        for floor in ("app_guild_base", "guest_base"):
            for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                held = (
                    await conn.execute(
                        text(
                            "SELECT has_table_privilege(:floor, "
                            f"'public.guild_member_profiles', '{verb}')"
                        ),
                        {"floor": floor},
                    )
                ).scalar()
                assert held == (verb == "SELECT"), (
                    f"{floor} {'lacks' if verb == 'SELECT' else 'holds'} {verb} "
                    "on the guild projection"
                )

        # The cross-guild profile page reads ``user_profiles``, which has no
        # name in it, so the platform floor has no business with this one.
        base_can_read = (
            await conn.execute(
                text(
                    "SELECT has_table_privilege(:role, "
                    "'public.guild_member_profiles', 'SELECT')"
                ),
                {"role": base},
            )
        ).scalar()
        assert not base_can_read, (
            f"{base} must not read the guild projection — a member's name is "
            "readable inside its guild, not from the platform path"
        )
