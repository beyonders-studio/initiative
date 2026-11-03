"""A member shares an item to the deployment's marketplace.

The share starts inside a community, where the item is read on the member's
own session, and ends as a ``local`` listing: waiting for the owner's review,
unless the owner lets members publish directly. Once on the shelf it installs
like any other tool listing.
"""

import pytest

from app.core.messages import MarketplaceMessages
from app.models.platform.guild import CommunityRole
from app.testing import (
    create_counter,
    create_counter_group,
    create_task,
)

PENDING_URL = "/api/v1/marketplace/local/pending"
SETTINGS_URL = "/api/v1/marketplace/local/settings"
MINE_URL = "/api/v1/marketplace/local/mine"


async def _counter_group(session, actor, *counts: float):
    group = await create_counter_group(
        session, actor.initiative, actor.user, name="Our tally"
    )
    for index, count in enumerate(counts):
        await create_counter(session, group, name=f"Counter {index}", count=count)
    return group


async def _share(client, actor, images=(), **body):
    """Share as the page does: the fields as a form, the pictures as files."""
    fields = {
        "kind": "counter_group",
        "name": "Party tally",
        "description": "Keep score.",
        **body,
    }
    return await client.post(
        actor.g("/marketplace/share"),
        data={key: str(value) for key, value in fields.items() if value is not None},
        files=[
            ("images", (f"picture{i}.png", data, "image/png"))
            for i, data in enumerate(images)
        ]
        or None,
        headers=actor.headers,
    )


async def _shelf(client, actor) -> list[str]:
    response = await client.get(
        actor.g("/marketplace/listings"),
        params={"kind": "counter_group"},
        headers=actor.headers,
    )
    assert response.status_code == 200, response.text
    return [item["uid"] for item in response.json()["items"]]


class TestSharing:
    async def test_a_share_waits_for_review_and_is_not_offered(
        self, client, acting_user, session
    ):
        member = await acting_user(guild_role=CommunityRole.member, initiative=True)
        group = await _counter_group(session, member, 3, 5)

        response = await _share(client, member, entity_id=group.id)

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["awaiting_review"] is True
        assert body["public_id"] == f"local.{body['uid'].lower()}"
        assert body["uid"] not in await _shelf(client, member)

    async def test_the_owner_approves_it_onto_the_shelf(
        self, client, acting_user, session
    ):
        member = await acting_user(guild_role=CommunityRole.member, initiative=True)
        owner = await acting_user("owner")
        group = await _counter_group(session, member, 3, 5)
        uid = (await _share(client, member, entity_id=group.id)).json()["uid"]

        pending = await client.get(PENDING_URL, headers=owner.headers)
        assert pending.status_code == 200, pending.text
        [waiting] = [item for item in pending.json() if item["uid"] == uid]
        assert waiting["is_new_listing"] is True
        assert waiting["definition"]["type"] == "initiative-counter-group"

        approved = await client.post(
            f"/api/v1/marketplace/local/{uid}/versions/1.0.0/approve",
            headers=owner.headers,
        )
        assert approved.status_code == 204, approved.text
        assert uid in await _shelf(client, member)

        detail = await client.get(
            member.g(f"/marketplace/listings/by-uid/{uid}"), headers=member.headers
        )
        # Published under the member's handle, as a listing from this deployment.
        assert detail.json()["source"] == "local"
        assert "#" in detail.json()["publisher"]

    async def test_a_refused_share_is_gone(self, client, acting_user, session):
        member = await acting_user(guild_role=CommunityRole.member, initiative=True)
        owner = await acting_user("owner")
        group = await _counter_group(session, member, 1)
        uid = (await _share(client, member, entity_id=group.id)).json()["uid"]

        refused = await client.post(
            f"/api/v1/marketplace/local/{uid}/versions/1.0.0/refuse",
            headers=owner.headers,
        )

        assert refused.status_code == 204, refused.text
        pending = await client.get(PENDING_URL, headers=owner.headers)
        assert uid not in [item["uid"] for item in pending.json()]
        mine = await client.get(MINE_URL, headers=member.headers)
        assert uid not in [item["uid"] for item in mine.json()]

    async def test_reviewing_is_the_owners(self, client, acting_user, session):
        member = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        group = await _counter_group(session, member, 1)
        uid = (await _share(client, member, entity_id=group.id)).json()["uid"]

        # A guild admin runs a community, not the deployment's shelf.
        assert (
            await client.get(PENDING_URL, headers=member.headers)
        ).status_code == 403
        approved = await client.post(
            f"/api/v1/marketplace/local/{uid}/versions/1.0.0/approve",
            headers=member.headers,
        )
        assert approved.status_code == 403

    async def test_members_may_publish_directly_when_the_owner_allows_it(
        self, client, acting_user, session
    ):
        member = await acting_user(guild_role=CommunityRole.member, initiative=True)
        owner = await acting_user("owner")
        group = await _counter_group(session, member, 2)
        switched = await client.put(
            SETTINGS_URL,
            json={"members_publish_directly": True},
            headers=owner.headers,
        )
        assert switched.status_code == 200, switched.text

        response = await _share(client, member, entity_id=group.id)

        assert response.json()["awaiting_review"] is False
        assert response.json()["uid"] in await _shelf(client, member)

    async def test_the_shared_listing_installs_in_another_community(
        self, client, acting_user, session
    ):
        member = await acting_user(guild_role=CommunityRole.member, initiative=True)
        owner = await acting_user("owner")
        group = await _counter_group(session, member, 3, 5)
        uid = (await _share(client, member, entity_id=group.id)).json()["uid"]
        await client.post(
            f"/api/v1/marketplace/local/{uid}/versions/1.0.0/approve",
            headers=owner.headers,
        )
        elsewhere = await acting_user(guild_role=CommunityRole.member, initiative=True)

        response = await client.post(
            elsewhere.g(f"/marketplace/listings/by-uid/{uid}/install"),
            json={"initiative_id": elsewhere.initiative.id},
            headers=elsewhere.headers,
        )

        assert response.status_code == 201, response.text
        assert response.json()["result"]["entity_title"] == "Party tally"
        assert response.json()["result"]["created"].get("counters") == 2


class TestVersions:
    async def test_the_member_who_shared_it_publishes_a_new_version(
        self, client, acting_user, session
    ):
        member = await acting_user(guild_role=CommunityRole.member, initiative=True)
        group = await _counter_group(session, member, 1)
        uid = (await _share(client, member, entity_id=group.id)).json()["uid"]

        again = await _share(
            client, member, entity_id=group.id, listing_uid=uid, name="Renamed"
        )

        assert again.status_code == 201, again.text
        assert again.json()["version"] == "2.0.0"
        mine = await client.get(MINE_URL, headers=member.headers)
        [listing] = [item for item in mine.json() if item["uid"] == uid]
        # The name is the listing's; a new version does not change it.
        assert listing["name"] == "Party tally"
        assert listing["pending_versions"] == ["1.0.0", "2.0.0"]

    async def test_nobody_else_publishes_a_version_of_it(
        self, client, acting_user, session
    ):
        member = await acting_user(guild_role=CommunityRole.member, initiative=True)
        group = await _counter_group(session, member, 1)
        uid = (await _share(client, member, entity_id=group.id)).json()["uid"]
        other = await acting_user(guild_role=CommunityRole.member, initiative=True)
        theirs = await _counter_group(session, other, 1)

        response = await _share(client, other, entity_id=theirs.id, listing_uid=uid)

        assert response.status_code == 404
        assert response.json()["detail"] == MarketplaceMessages.LISTING_NOT_FOUND


class TestWhatIsShared:
    async def test_a_shared_project_names_nobody(self, client, acting_user, session):
        member = await acting_user(
            guild_role=CommunityRole.member, initiative=True, project=True
        )
        await create_task(session, member.project, assignees=[member.user])
        owner = await acting_user("owner")

        response = await _share(
            client, member, kind="project", entity_id=member.project.id
        )

        assert response.status_code == 201, response.text
        pending = await client.get(PENDING_URL, headers=owner.headers)
        [waiting] = [
            item for item in pending.json() if item["uid"] == response.json()["uid"]
        ]
        definition = waiting["definition"]
        assert definition["exported_by_handle"] is None
        assert all(task["assignee_handles"] == [] for task in definition["tasks"])

    async def test_an_item_the_member_cannot_read_is_not_shared(
        self, client, acting_user, session
    ):
        owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        group = await _counter_group(session, owner, 1)
        outsider = await acting_user(guild_role=CommunityRole.member, guild=owner.guild)

        response = await _share(client, outsider, entity_id=group.id)

        assert response.status_code in (403, 404)


class TestTakingItDown:
    async def test_the_member_withdraws_what_they_shared(
        self, client, acting_user, session
    ):
        member = await acting_user(guild_role=CommunityRole.member, initiative=True)
        owner = await acting_user("owner")
        group = await _counter_group(session, member, 1)
        uid = (await _share(client, member, entity_id=group.id)).json()["uid"]
        await client.post(
            f"/api/v1/marketplace/local/{uid}/versions/1.0.0/approve",
            headers=owner.headers,
        )

        response = await client.delete(
            f"/api/v1/marketplace/local/{uid}", headers=member.headers
        )

        assert response.status_code == 204, response.text
        assert uid not in await _shelf(client, member)

    async def test_nobody_else_takes_it_down(self, client, acting_user, session):
        member = await acting_user(guild_role=CommunityRole.member, initiative=True)
        group = await _counter_group(session, member, 1)
        uid = (await _share(client, member, entity_id=group.id)).json()["uid"]
        other = await acting_user(guild_role=CommunityRole.member)

        response = await client.delete(
            f"/api/v1/marketplace/local/{uid}", headers=other.headers
        )

        assert response.status_code == 404


@pytest.fixture(autouse=True)
async def _reset_publish_directly(session):
    """The switch is one of the deployment's rules; leave it off."""
    yield
    from app.services.platform import rules

    await rules.put(session, "marketplace_members_publish_directly", False)
    await session.commit()


class TestPictures:
    """A community's pictures never leave it. A listing shows only pictures
    somebody uploaded to the marketplace for it."""

    async def _media_count(self, session) -> int:
        from sqlalchemy import func
        from sqlmodel import select

        from app.models.platform.marketplace_registry import MarketplaceMedia

        return (await session.exec(select(func.count(MarketplaceMedia.id)))).one()

    async def test_a_files_picture_stays_behind(self, client, acting_user, session):
        from app.services.storage import get_guild_storage
        from app.testing import create_file, png_bytes

        member = await acting_user(guild_role=CommunityRole.member, initiative=True)
        owner = await acting_user("owner")
        get_guild_storage(member.guild.id).write(
            "picture.png", png_bytes(2, 2), content_type="image/png"
        )
        paragraph = {
            "type": "paragraph",
            "children": [
                {"type": "image", "src": f"/uploads/{member.guild.id}/picture.png"},
                {
                    "type": "link",
                    "url": f"/uploads/{member.guild.id}/picture.png",
                    "children": [{"type": "text", "text": "the picture"}],
                },
            ],
        }
        file = await create_file(
            session,
            member.initiative,
            member.user,
            content={"root": {"type": "root", "children": [paragraph]}},
        )

        shared = await _share(
            client, member, kind="file", entity_id=file.id, name="Handout"
        )

        assert shared.status_code == 201, shared.text
        pending = await client.get(PENDING_URL, headers=owner.headers)
        [waiting] = [
            item for item in pending.json() if item["uid"] == shared.json()["uid"]
        ]
        children = waiting["definition"]["content"]["root"]["children"][0]["children"]
        assert [child["type"] for child in children] == ["link"]
        assert children[0]["url"] == ""

    async def test_the_member_uploads_the_listings_pictures(
        self, client, acting_user, session
    ):
        from app.services.marketplace.media import MEDIA_URL_PREFIX
        from app.testing import png_bytes

        member = await acting_user(guild_role=CommunityRole.member, initiative=True)
        group = await _counter_group(session, member, 1)

        shared = await _share(
            client,
            member,
            entity_id=group.id,
            images=[png_bytes(2, 2), png_bytes(3, 3)],
        )

        assert shared.status_code == 201, shared.text
        mine = await client.get(MINE_URL, headers=member.headers)
        [listing] = [
            item for item in mine.json() if item["uid"] == shared.json()["uid"]
        ]
        assert len(listing["images"]) == 2
        assert all(path.startswith(MEDIA_URL_PREFIX) for path in listing["images"])

    async def test_a_file_that_is_not_a_picture_is_refused(
        self, client, acting_user, session
    ):
        member = await acting_user(guild_role=CommunityRole.member, initiative=True)
        group = await _counter_group(session, member, 1)

        shared = await _share(
            client, member, entity_id=group.id, images=[b"not a picture"]
        )

        assert shared.status_code == 422
        assert shared.json()["detail"] == MarketplaceMessages.SHARE_IMAGE_INVALID

    async def test_uploading_a_picture_for_a_listing_file_is_the_owners(
        self, client, acting_user
    ):
        from app.testing import png_bytes

        member = await acting_user(guild_role=CommunityRole.member)
        response = await client.post(
            "/api/v1/marketplace/local/media",
            files={"file": ("tile.png", png_bytes(4, 4), "image/png")},
            headers=member.headers,
        )
        assert response.status_code == 403
