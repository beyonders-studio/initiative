"""What a client is told it may write.

Two answers describe the query surface without reading anybody's rows: the
fields of a dataset, and the words a statement may contain. Both exist so that
a client helping somebody write a query offers exactly what the validator
accepts — so what is worth testing is not the contents of either list but that
neither can drift from the thing it describes.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.tenant_endpoints import field_catalog
from app.core.tool_set import BUILTIN_TOOLS
from app.models.platform.guild import CommunityRole
from app.services.fields import dataset
from app.services.fields.registry import dataset_names
from app.services.query.resolve import PLUGIN, SHEET, QueryError, resolve
from app.testing import install_tool_plugin


def read_query_vocabulary() -> Any:
    """The vocabulary of a community with only the built-in tools."""
    context: Any = SimpleNamespace(tools=BUILTIN_TOOLS)
    return field_catalog.read_query_vocabulary(context)


class TestTheVocabularyIsTheValidatorsOwn:
    def test_every_dataset_offered_can_be_read(self):
        """Named with a field it actually declares, not with ``id``: a join
        table is keyed by the two things it relates and has no id of its own."""
        for name in read_query_vocabulary().datasets:
            field = next(
                spec.name for spec in dataset(name).fields if spec.column is not None
            )
            resolve(f"SELECT {field} FROM {name}")

    def test_every_function_offered_is_one_the_validator_accepts(self):
        """Called with an argument each takes, so a refusal here is the name
        being unknown rather than the call being wrong. ``sheet`` is called
        where it is written, in ``FROM``."""
        calls = {
            "count": "count(*)",
            "now": "now()",
            "concat": "concat(title, title)",
            "date_trunc": "date_trunc('day', created_at)",
            "extract": "extract(YEAR FROM created_at)",
            "round": "round(position)",
        }
        for function in read_query_vocabulary().functions:
            call = calls.get(function, f"{function}(position)")
            sql = {
                SHEET: "SELECT region FROM sheet('Budget')",
                PLUGIN: "SELECT status FROM plugin('acme.shop', 'orders')",
            }.get(function, f"SELECT {call} AS v FROM tasks")
            try:
                resolve(sql)
            except QueryError as refused:
                pytest.fail(f"{function} is offered but refused: {refused}")

    def test_a_function_it_does_not_offer_is_refused(self):
        """The other direction: the list is the whole of what is accepted, not
        a helpful subset of something wider."""
        assert "pg_sleep" not in read_query_vocabulary().functions
        with pytest.raises(QueryError):
            resolve("SELECT pg_sleep(10) AS v FROM tasks")

    def test_it_offers_every_dataset_the_registry_declares(self):
        assert set(read_query_vocabulary().datasets) == set(dataset_names())


class TestReadingIt:
    async def test_a_member_can_read_the_vocabulary(self, client, acting_user):
        actor = await acting_user(guild_role=CommunityRole.member)
        response = await client.get(actor.g("/query/vocabulary"), headers=actor.headers)
        assert response.status_code == 200
        body = response.json()
        assert "tasks" in body["datasets"]
        assert "date_trunc" in body["functions"]

    async def test_it_is_not_public(self, client, acting_user):
        actor = await acting_user(guild_role=CommunityRole.member)
        response = await client.get(actor.g("/query/vocabulary"))
        assert response.status_code == 401

    async def test_it_is_read_inside_a_community_its_reader_is_in(
        self, client, acting_user
    ):
        actor = await acting_user(guild_role=CommunityRole.member)
        stranger = await acting_user(guild_role=CommunityRole.member)
        for path in ("/query/vocabulary", "/fields/tasks"):
            response = await client.get(actor.g(path), headers=stranger.headers)
            assert response.status_code == 403, path

    async def test_the_field_catalog_names_its_dataset(self, client, acting_user):
        actor = await acting_user(guild_role=CommunityRole.member)
        response = await client.get(actor.g("/fields/tasks"), headers=actor.headers)
        assert response.status_code == 200
        body = response.json()
        assert body["dataset"] == "tasks"
        assert {field["name"] for field in body["fields"]} >= {"title", "priority"}

    async def test_a_dataset_nobody_declared_is_not_found(self, client, acting_user):
        actor = await acting_user(guild_role=CommunityRole.member)
        response = await client.get(actor.g("/fields/pg_shadow"), headers=actor.headers)
        assert response.status_code == 404
        assert response.json()["detail"] == "QUERY_UNKNOWN_RELATION"

    async def test_an_installed_tools_datasets_are_offered_there_alone(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        """A tool plug-in's datasets are its community's: listed and described
        where it is installed, and not found anywhere else."""
        member = await acting_user(guild_role=CommunityRole.member, initiative=True)
        await session.commit()
        seat = await acting_user(
            guild=member.guild, guild_role=CommunityRole.superadmin
        )
        await install_tool_plugin(client, session, seat)
        elsewhere = await acting_user(guild_role=CommunityRole.member)

        vocabulary = await client.get(
            member.g("/query/vocabulary"), headers=member.headers
        )
        assert vocabulary.status_code == 200
        installed = set(vocabulary.json()["datasets"]) - set(dataset_names())
        assert installed, "the installed tool brings no dataset"

        for name in installed:
            response = await client.get(
                member.g(f"/fields/{name}"), headers=member.headers
            )
            assert response.status_code == 200, response.text
            assert response.json()["dataset"] == name
            assert response.json()["fields"], name

            response = await client.get(
                elsewhere.g(f"/fields/{name}"), headers=elsewhere.headers
            )
            assert response.status_code == 404, name

        response = await client.get(
            elsewhere.g("/query/vocabulary"), headers=elsewhere.headers
        )
        assert set(response.json()["datasets"]) == set(dataset_names())
