"""What a client is told it may write.

Two answers describe the query surface without reading anybody's rows: the
fields of a dataset, and the words a statement may contain. Both exist so that
a client helping somebody write a query offers exactly what the validator
accepts — so what is worth testing is not the contents of either list but that
neither can drift from the thing it describes.
"""

import pytest

from app.api.v1.platform_endpoints.field_catalog import read_query_vocabulary
from app.models.platform.guild import CommunityRole
from app.services.fields import dataset
from app.services.fields.registry import dataset_names
from app.services.query.resolve import SHEET, QueryError, resolve


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
        being unknown rather than the call being wrong."""
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
            # ``sheet`` is read from, so it is called where a relation goes.
            sql = (
                f"SELECT count(*) AS v FROM {SHEET}('Budget')"
                if function == SHEET
                else f"SELECT {call} AS v FROM tasks"
            )
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
        response = await client.get("/api/v1/query/vocabulary", headers=actor.headers)
        assert response.status_code == 200
        body = response.json()
        assert "tasks" in body["datasets"]
        assert "date_trunc" in body["functions"]

    async def test_it_takes_no_guild(self, client, acting_user):
        """It describes the deployment rather than anybody's rows, so it is not
        addressed inside a guild — the same answer everywhere."""
        actor = await acting_user(guild_role=CommunityRole.member)
        response = await client.get("/api/v1/query/vocabulary", headers=actor.headers)
        assert response.status_code == 200

    async def test_it_is_not_public(self, client):
        response = await client.get("/api/v1/query/vocabulary")
        assert response.status_code == 401

    async def test_the_field_catalog_names_its_dataset(self, client, acting_user):
        actor = await acting_user(guild_role=CommunityRole.member)
        response = await client.get("/api/v1/fields/tasks", headers=actor.headers)
        assert response.status_code == 200
        body = response.json()
        assert body["dataset"] == "tasks"
        assert {field["name"] for field in body["fields"]} >= {"title", "priority"}

    async def test_a_dataset_nobody_declared_is_refused(self, client, acting_user):
        actor = await acting_user(guild_role=CommunityRole.member)
        response = await client.get("/api/v1/fields/pg_shadow", headers=actor.headers)
        assert response.status_code == 422
