"""A tool plug-in's tool: built from its declaration, created in the
community that installs it, and ruled as a built-in tool is."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.plugin_tools import provisioned_tools
from app.db.schema_provisioning import guild_schema_name
from app.models.platform.guild import CommunityRole
from app.testing import COUNTERS_UID, install_tool_plugin


async def test_install_creates_the_declared_tables(
    client: AsyncClient, session: AsyncSession, acting_user
):
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    await install_tool_plugin(client, session, seat)
    tools = await provisioned_tools(seat.guild.id)
    schema = guild_schema_name(seat.guild.id)
    check = await session.scalar(
        sa.text(
            "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c"
            " JOIN pg_namespace n ON n.oid = c.connamespace"
            " WHERE n.nspname = :s AND c.conname = 'ck_initiative_rules_key'"
        ),
        {"s": schema},
    )
    stamp = await session.scalar(
        sa.text("SELECT obj_description(to_regnamespace(:s), 'pg_namespace')"),
        {"s": schema},
    )
    assert tools.installed, (stamp, check)
