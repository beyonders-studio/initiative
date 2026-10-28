"""A plug-in that asks for tokens, for the suites that exercise the token endpoint
and the routes an installation token reaches.

Holds the plug-in's Ed25519 keypair, the key set its registration
publishes, the client assertion it signs, and an install set up the way a
community sets one up: placed in an initiative, granted scopes by its seat,
and registered by the operator.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

import jwt
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from jwt.algorithms import OKPAlgorithm
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.plugin_access_token import seal_install_token
from app.core.plugin_scopes import ALL_SCOPES

from app.core.tools import Tool
from app.models.platform.guild import CommunityRole
from app.models.tenant.plugin_placement import PluginPlacement
from app.models.tenant.file import File
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing.factories import (
    create_plugin_service_registration,
    create_guild_plugin,
    create_initiative,
)
from app.testing.routing import route_as
from app.testing.schema_harness import route_session_to_guild

__all__ = [
    "CLIENT",
    "KID",
    "LISTING",
    "InstalledPlugin",
    "assert_names_nobody",
    "client_jwks",
    "install_plugin",
    "install_headers",
    "lift_person_and_guild_ids",
    "mint_client_assertion",
    "share_with_members",
]

CLIENT = "tests.token-client"
LISTING = "TOKENCLIENT001"
KID = "token-client-1"

#: The test plug-in's key: Ed25519, the one kind a plug-in signs with.
_key = ed25519.Ed25519PrivateKey.generate()
#: A key the plug-in never registered, for assertions that must be refused.
_foreign_rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def client_jwks() -> dict[str, Any]:
    """The key set the plug-in's registration publishes: its one Ed25519 key."""
    entry = json.loads(OKPAlgorithm.to_jwk(_key.public_key()))
    entry["kid"] = KID
    return {"keys": [entry]}


def mint_client_assertion(
    *,
    audience: str,
    key: str = "plugin",
    client_id: str = CLIENT,
    kid: Optional[str] = None,
    algorithm: Optional[str] = None,
    issued_at: Optional[float] = None,
    lifetime: int = 60,
    jti: Optional[str] = None,
    subject: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> str:
    """A client assertion signed by the plug-in's key (EdDSA).

    ``key="foreign-rsa"`` signs with an RSA key the plug-in never registered,
    RS256, under the plug-in's ``kid`` unless another is given: what an
    attacker holding some other key would send. ``extra`` adds claims, as a
    member grant's ``installation`` and ``purpose``.
    """
    private, default_alg = (
        (_key, "EdDSA") if key == "plugin" else (_foreign_rsa_key, "RS256")
    )
    iat = int(time.time() if issued_at is None else issued_at)
    claims = {
        "iss": client_id,
        "sub": client_id if subject is None else subject,
        "aud": audience,
        "jti": jti or secrets.token_urlsafe(16),
        "iat": iat,
        "exp": iat + lifetime,
        **(extra or {}),
    }
    return jwt.encode(
        claims,
        private,
        algorithm=algorithm or default_alg,
        headers={"kid": kid or KID, "typ": "JWT"},
    )


@dataclass
class InstalledPlugin:
    """What a test names: the seat, the community, the install, the initiative
    it is placed in and one it is not."""

    seat: Any
    plugin: GuildPlugin
    placed: Any
    unplaced: Any

    @property
    def guild(self) -> Any:
        return self.seat.guild

    @property
    def public_id(self) -> str:
        """The plug-in, whose sector the install's references are in."""
        return self.plugin.definition["service"]["public_id"]


async def install_plugin(
    session: AsyncSession,
    acting_user: Any,
    role_session: Any,
    *,
    granted: Sequence[str],
    client_id: str = CLIENT,
    listing_uid: str = LISTING,
    register: bool = True,
    enabled: bool = True,
    requested: Optional[Sequence[str]] = None,
    declares: Optional[Mapping[str, Any]] = None,
) -> InstalledPlugin:
    """An install of ``client_id``'s listing, placed in one of two
    initiatives and granted ``granted`` by the community's seat, with the
    operator's registration publishing :func:`client_jwks`.

    The pinned manifest requests ``requested``, every scope by default, so
    the grant is what decides what a token carries. ``declares`` adds to it,
    such as its ``fields``."""
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    unplaced = await create_initiative(session, seat.guild, seat.user, name="B")
    plugin = await create_guild_plugin(
        session,
        seat.guild,
        seat.user,
        definition={
            "plugin_kind": "service",
            "service": {
                "public_id": client_id,
                "protocol": 1,
                "scopes": list(ALL_SCOPES if requested is None else requested),
            },
            **(declares or {}),
        },
        listing_uid=listing_uid,
    )
    if register:
        await create_plugin_service_registration(
            session,
            public_id=client_id,
            listing_uid=listing_uid,
            enabled=enabled,
            jwks=client_jwks(),
            scope_ceiling=list(ALL_SCOPES if requested is None else requested),
        )

    await route_session_to_guild(session, seat.guild.id)
    session.add(PluginPlacement(install_id=plugin.id, initiative_id=seat.initiative.id))
    await session.commit()

    if granted:
        s = await role_session("app_user")
        await route_as(s, user_id=seat.user.id, guild_id=seat.guild.id)
        row = (
            await s.exec(select(GuildPlugin).where(GuildPlugin.id == plugin.id))
        ).one()
        row.granted_scopes = list(granted)
        s.add(row)
        await s.commit()
    return InstalledPlugin(
        seat=seat, plugin=plugin, placed=seat.initiative, unplaced=unplaced
    )


async def share_with_members(
    session: AsyncSession, file: File, initiative_id: int
) -> None:
    """Share ``file`` with every member of its initiative, which an
    install placed there counts as."""
    session.add(
        ResourceGrant(
            resource_type=Tool.file.value,
            resource_id=file.id,
            all_initiative_members=True,
            level=ResourceAccessLevel.read,
            initiative_id=initiative_id,
        )
    )
    await session.commit()


def install_headers(
    installed: InstalledPlugin,
    scopes: Sequence[str],
    *,
    initiative_id: Optional[int] = None,
    install_id: Optional[int] = None,
    client_id: str = CLIENT,
) -> dict[str, str]:
    """The ``Authorization`` header of an installation token for ``installed``,
    carrying ``scopes`` and narrowed to ``initiative_id`` when one is given."""
    token, _exp = seal_install_token(
        guild_id=installed.guild.id,
        install_id=install_id if install_id is not None else installed.plugin.id,
        client_id=client_id,
        scopes=frozenset(scopes),
        initiative_id=initiative_id,
    )
    return {"Authorization": f"Bearer {token}"}


#: Where people's and communities' ids start in a test that looks for them in a
#: response: far above any id another table will reach in one test, so finding
#: the digits anywhere in a body means somebody's id is there.
_PERSON_ID_FLOOR = 7_000_000
_GUILD_ID_FLOOR = 8_000_000


async def lift_person_and_guild_ids(session: AsyncSession) -> None:
    """Start the ids of the people and communities made after this far above
    every other row id, so :func:`assert_names_nobody` can tell one in a
    response wherever it sits — a field, a nested object, a URL. Call it
    before creating anybody."""
    offset = secrets.randbelow(100_000)
    await session.exec(
        text("SELECT setval('public.users_id_seq', :v)"),
        params={"v": _PERSON_ID_FLOOR + offset},
    )
    await session.exec(
        text("SELECT setval('public.guilds_id_seq', :v)"),
        params={"v": _GUILD_ID_FLOOR + offset},
    )
    await session.commit()


def assert_names_nobody(body: str, ids: Sequence[int]) -> None:
    """Fail if any of ``ids`` — people's or a community's, lifted by
    :func:`lift_person_and_guild_ids` — appears anywhere in ``body``."""
    found = [value for value in ids if str(value) in body]
    assert not found, f"the response names {found}: {body[:2000]}"


async def kept_plugin_values(session: AsyncSession) -> dict[tuple, tuple]:
    """Every value the plug-ins keep in the routed community, as each plug-in
    wrote it and whether it is shown, by ``(entity_type, entity_id, key,
    ref)``."""
    from app.models.tenant.metadata import MetadataDefinition, MetadataValue
    from app.services.tenant import metadata

    rows = await session.exec(
        select(MetadataDefinition, MetadataValue)
        .join(MetadataValue, MetadataValue.property_id == MetadataDefinition.id)
        .where(MetadataDefinition.install_id.is_not(None))
        .execution_options(populate_existing=True)
    )
    return {
        (row.entity_type, row.entity_id, defn.key, row.ref): (
            metadata._told(defn, row, metadata._ROW_IDS),
            row.entity_type in defn.shown_on,
        )
        for defn, row in rows
    }
