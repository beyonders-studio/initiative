"""Integration tests for guild icons and banners.

These are the only guild media a stranger can be shown, so most of what is
asserted here is the boundary: which variant reaches whom, and that everything
else is a 404 rather than a 403 — an unlisted guild has published nothing, its
existence at a given id included.
"""

import io
import struct

import pytest
from httpx2 import AsyncClient
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import (
    DEFAULT_BANNER,
    CommunityRole,
    CommunityStatus,
    Guild,
)
from app.models.platform.guild_image import (
    IMAGE_SPECS,
    GuildImage,
    GuildImageVariant,
)
from app.models.platform.user import UserRole
from app.services.platform import rules
from app.testing import guild_administration
from app.testing.factories import (
    create_access_grant,
    create_user,
    get_auth_headers,
)


def _png(width: int, height: int, padding: int = 0) -> bytes:
    """A PNG whose header states these dimensions.

    Only the header is read — nothing decodes these bytes — so the image data
    is whatever makes the file the size a given test needs.
    """
    header = (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    )
    return header + b"\x00" * padding


def _spec_png(variant: GuildImageVariant, padding: int = 0) -> bytes:
    spec = IMAGE_SPECS[variant]
    return _png(spec.width, spec.height, padding)


def _banner(**overrides: str) -> dict[str, str]:
    """A whole banner to PATCH: the defaults, with whatever a test changes.

    The endpoint replaces the banner rather than merging into it, so every
    field is named on every write — the panel that sends this is showing all
    four.
    """
    return {**DEFAULT_BANNER, **overrides}


def _banner_files(
    full: bytes | None = None, card: bytes | None = None
) -> dict[str, tuple[str, io.BytesIO, str]]:
    return {
        "full": (
            "full.png",
            io.BytesIO(full if full is not None else _spec_png(GuildImageVariant.full)),
            "image/png",
        ),
        "card": (
            "card.png",
            io.BytesIO(card if card is not None else _spec_png(GuildImageVariant.card)),
            "image/png",
        ),
    }


def _icon_files(
    icon: bytes | None = None,
) -> dict[str, tuple[str, io.BytesIO, str]]:
    return {
        "icon": (
            "icon.png",
            io.BytesIO(icon if icon is not None else _spec_png(GuildImageVariant.icon)),
            "image/png",
        )
    }


async def _set_icon(client: AsyncClient, guild_id: int, headers: dict) -> dict:
    response = await client.put(
        f"/api/v1/communities/{guild_id}/icon", headers=headers, files=_icon_files()
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _set_banner(client: AsyncClient, guild_id: int, headers: dict) -> dict:
    response = await client.put(
        f"/api/v1/communities/{guild_id}/banner", headers=headers, files=_banner_files()
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _list_as_community(session: AsyncSession, guild: Guild) -> Guild:
    guild.join_policy = "open"
    guild.categories = ["other"]
    guild.has_adult_content = False
    session.add(guild)
    await session.commit()
    await session.refresh(guild)
    return guild


async def _variant_url(
    session: AsyncSession, guild_id: int, variant: GuildImageVariant
) -> str:
    digest = (
        await session.exec(
            select(GuildImage.sha256).where(
                GuildImage.guild_id == guild_id,
                GuildImage.variant == variant.value,
            )
        )
    ).one()
    return f"/api/v1/communities/{guild_id}/image/{digest}"


async def _card_url(session: AsyncSession, guild_id: int) -> str:
    return await _variant_url(session, guild_id, GuildImageVariant.card)


@pytest.fixture
async def community_directory_on(session: AsyncSession) -> None:
    await rules.put(session, "community_directory_enabled", True)
    await session.commit()


# --- setting one -------------------------------------------------------------


async def test_admin_sets_banner_and_gets_its_url_back(
    client: AsyncClient, acting_user, session: AsyncSession
):
    """One upload, two renditions, and the reply already names the full one.
    The guild list names neither before, then the full one for the front page
    and the card one for the switcher's cards."""
    a = await acting_user(guild_role=CommunityRole.admin)

    async def entry() -> dict:
        response = await client.get("/api/v1/communities/", headers=a.headers)
        assert response.status_code == 200
        return next(g for g in response.json() if g["id"] == a.guild.id)

    # No guild is ever without a banner: the default, with no artwork. The
    # roster and how many are here now ride in the same payload.
    before = await entry()
    assert before["banner"] == {"image_url": None, **DEFAULT_BANNER}
    assert before["banner_card_url"] is None
    assert before["member_count"] == 1
    assert before["online_count"] == 0

    payload = await _set_banner(client, a.guild.id, a.headers)

    assert payload["banner"]["image_url"].startswith(
        f"/api/v1/communities/{a.guild.id}/image/"
    )
    after = await entry()
    assert after["banner"]["image_url"] == payload["banner"]["image_url"]
    assert after["banner_card_url"] == await _card_url(session, a.guild.id)


async def test_member_cannot_set_the_banner(client: AsyncClient, acting_user):
    """Branding is the guild admin's, like the name and the icon."""
    a = await acting_user(guild_role=CommunityRole.member)

    response = await client.put(
        f"/api/v1/communities/{a.guild.id}/banner",
        headers=a.headers,
        files=_banner_files(),
    )

    assert response.status_code == 403


async def test_replacing_a_banner_leaves_one_of_each_rendition(
    client: AsyncClient, acting_user, session: AsyncSession
):
    """The old renditions go with the new ones arriving, not afterwards. The
    digest is in the path, so a stale URL is a miss rather than a different
    picture under a cache key promised to be immutable."""
    a = await acting_user(guild_role=CommunityRole.admin)
    first = await _set_banner(client, a.guild.id, a.headers)

    response = await client.put(
        f"/api/v1/communities/{a.guild.id}/banner",
        headers=a.headers,
        files=_banner_files(full=_spec_png(GuildImageVariant.full, padding=64)),
    )
    assert response.status_code == 200

    rows = (
        await session.exec(
            select(GuildImage.variant).where(GuildImage.guild_id == a.guild.id)
        )
    ).all()
    assert sorted(rows) == ["card", "full"]
    assert (
        await client.get(first["banner"]["image_url"], headers=a.headers)
    ).status_code == 404


async def test_clearing_a_banner_removes_both_renditions(
    client: AsyncClient, acting_user, session: AsyncSession
):
    a = await acting_user(guild_role=CommunityRole.admin)
    await _set_banner(client, a.guild.id, a.headers)

    response = await client.delete(
        f"/api/v1/communities/{a.guild.id}/banner", headers=a.headers
    )

    assert response.status_code == 200
    assert response.json()["banner"]["image_url"] is None
    rows = (
        await session.exec(select(GuildImage).where(GuildImage.guild_id == a.guild.id))
    ).all()
    assert rows == []


# --- what counts as a banner --------------------------------------------------


_SVG = b'<svg xmlns="http://www.w3.org/2000/svg"/>'


@pytest.mark.parametrize(
    "files,status,detail",
    [
        pytest.param(
            {
                "full": ("b.svg", _SVG, "image/svg+xml"),
                "card": ("c.svg", _SVG, "image/svg+xml"),
            },
            400,
            "IMAGE_INVALID",
            id="a banner is rendered, so it is raster only",
        ),
        pytest.param(
            {
                "full": ("full.png", b"not an image at all", "image/png"),
                "card": ("card.png", b"nor is this", "image/png"),
            },
            400,
            "IMAGE_INVALID",
            id="the bytes settle the format, not the declared type",
        ),
        pytest.param(
            _banner_files(card=_spec_png(GuildImageVariant.full)),
            400,
            "IMAGE_WRONG_SIZE",
            id="a card carrying the full image",
        ),
        pytest.param(
            _banner_files(full=_png(1200, 600)),
            400,
            "IMAGE_WRONG_RATIO",
            id="not four to one",
        ),
        pytest.param(
            _banner_files(
                card=_spec_png(
                    GuildImageVariant.card,
                    padding=IMAGE_SPECS[GuildImageVariant.card].max_bytes + 1,
                )
            ),
            413,
            "IMAGE_TOO_LARGE",
            id="an oversized rendition",
        ),
    ],
)
async def test_what_is_not_a_banner_is_refused(
    client: AsyncClient, acting_user, files, status: int, detail: str
):
    a = await acting_user(guild_role=CommunityRole.admin)

    response = await client.put(
        f"/api/v1/communities/{a.guild.id}/banner", headers=a.headers, files=files
    )

    assert response.status_code == status
    assert response.json()["detail"] == detail


# --- who may fetch one --------------------------------------------------------


async def test_a_member_gets_both_renditions(
    client: AsyncClient, acting_user, session: AsyncSession
):
    a = await acting_user(guild_role=CommunityRole.admin)
    payload = await _set_banner(client, a.guild.id, a.headers)

    full = await client.get(payload["banner"]["image_url"], headers=a.headers)
    card = await client.get(await _card_url(session, a.guild.id), headers=a.headers)

    assert full.status_code == 200
    assert full.headers["content-type"].startswith("image/png")
    assert "private" in full.headers["cache-control"]
    assert card.status_code == 200
    # A banner needs a session.
    assert (await client.get(payload["banner"]["image_url"])).status_code == 401


async def test_a_stranger_gets_nothing_from_an_unlisted_guild(
    client: AsyncClient, acting_user, session: AsyncSession
):
    """Not in the directory and not in the guild: there is no banner or icon
    to have."""
    a = await acting_user(guild_role=CommunityRole.admin)
    payload = await _set_banner(client, a.guild.id, a.headers)
    await _set_icon(client, a.guild.id, a.headers)
    stranger = await create_user(session, email="stranger@example.com")
    headers = get_auth_headers(stranger)

    for url in (
        payload["banner"]["image_url"],
        await _card_url(session, a.guild.id),
        await _variant_url(session, a.guild.id, GuildImageVariant.icon),
    ):
        assert (await client.get(url, headers=headers)).status_code == 404


async def test_un_listing_a_guild_stops_serving_its_card(
    client: AsyncClient, acting_user, session: AsyncSession, community_directory_on
):
    """The card is what a listed guild published; the full banner is not. The
    listing is re-read per request, not inherited from the page that minted the
    URL."""
    a = await acting_user(guild_role=CommunityRole.admin)
    payload = await _set_banner(client, a.guild.id, a.headers)
    await _list_as_community(session, a.guild)
    stranger = await create_user(session, email="lingering@example.com")
    headers = get_auth_headers(stranger)
    url = await _card_url(session, a.guild.id)
    assert (await client.get(url, headers=headers)).status_code == 200
    full = await client.get(payload["banner"]["image_url"], headers=headers)
    assert full.status_code == 404

    a.guild.join_policy = "private"
    session.add(a.guild)
    await session.commit()

    assert (await client.get(url, headers=headers)).status_code == 404


async def test_a_suspended_guild_serves_nobody(
    client: AsyncClient, acting_user, session: AsyncSession, community_directory_on
):
    """Suspension takes the guild out of the directory and out of its members'
    reach, and the banner goes with it."""
    a = await acting_user(guild_role=CommunityRole.admin)
    payload = await _set_banner(client, a.guild.id, a.headers)
    await _list_as_community(session, a.guild)
    url = await _card_url(session, a.guild.id)
    stranger = await create_user(session, email="onlooker@example.com")

    a.guild.status = CommunityStatus.suspended.value
    session.add(a.guild)
    await session.commit()

    assert (
        await client.get(url, headers=get_auth_headers(stranger))
    ).status_code == 404
    assert (
        await client.get(payload["banner"]["image_url"], headers=a.headers)
    ).status_code == 404


# --- how it reaches the two surfaces ------------------------------------------


async def test_the_directory_names_the_card_rendition(
    client: AsyncClient, acting_user, session: AsyncSession, community_directory_on
):
    """A URL, never the bytes — a directory page is up to sixty cards. A card
    names both its pictures; it carries neither."""
    a = await acting_user(guild_role=CommunityRole.admin)
    await _set_banner(client, a.guild.id, a.headers)
    await _set_icon(client, a.guild.id, a.headers)
    await _list_as_community(session, a.guild)
    stranger = await create_user(session, email="visitor@example.com")

    response = await client.get(
        "/api/v1/communities/directory", headers=get_auth_headers(stranger)
    )

    assert response.status_code == 200
    card = next(g for g in response.json()["items"] if g["id"] == a.guild.id)
    assert card["banner"]["image_url"] == await _card_url(session, a.guild.id)
    assert card["icon_url"] == await _variant_url(
        session, a.guild.id, GuildImageVariant.icon
    )
    assert "icon_base64" not in card


async def test_deleting_a_guild_takes_its_banner(
    client: AsyncClient, acting_user, session: AsyncSession
):
    """The cascade off ``public.guilds``, asserted rather than assumed."""
    a = await acting_user(guild_role=CommunityRole.admin)
    await _set_banner(client, a.guild.id, a.headers)
    guild_id = a.guild.id

    # Raw, because the cascade under test is the database's: an ORM delete
    # would walk relationships into the guild's own schema, which this
    # (unrouted) session cannot see.
    await session.exec(
        text("DELETE FROM public.guilds WHERE id = :id"), params={"id": guild_id}
    )
    await session.commit()

    rows = (
        await session.exec(select(GuildImage).where(GuildImage.guild_id == guild_id))
    ).all()
    assert rows == []


async def test_a_settings_grant_reads_the_guild_with_its_pictures(
    client: AsyncClient, acting_user, session: AsyncSession
):
    """A settings rung has no entry in the guild list, so its read of the
    guild is where it learns the pictures it may be there to review — and
    every one of them is then served to it, unlisted guild or not."""
    a = await acting_user(guild_role=CommunityRole.admin)
    await _set_icon(client, a.guild.id, a.headers)
    await _set_banner(client, a.guild.id, a.headers)
    support = await create_user(session, role=UserRole.support)
    await create_access_grant(
        session, user=support, guild=a.guild, access_level="admin", purpose="settings"
    )
    headers = get_auth_headers(support)

    response = await client.get(f"/api/v1/communities/{a.guild.id}", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    urls = [
        payload["icon_url"],
        payload["banner"]["image_url"],
        payload["banner_card_url"],
    ]
    assert urls[2] == await _card_url(session, a.guild.id)
    for url in urls:
        assert (await client.get(url, headers=headers)).status_code == 200


async def test_a_pam_grantee_reads_the_full_banner(
    client: AsyncClient, acting_user, session: AsyncSession
):
    """Break-glass reaches a guild's front page as a member does, for its
    window."""
    a = await acting_user(guild_role=CommunityRole.admin)
    payload = await _set_banner(client, a.guild.id, a.headers)
    operator = await create_user(
        session, email="operator@example.com", role=UserRole.operator
    )
    await create_access_grant(session, user=operator, guild=a.guild)

    response = await client.get(
        payload["banner"]["image_url"], headers=get_auth_headers(operator)
    )

    assert response.status_code == 200


# --- the colour alternative ---------------------------------------------------


@pytest.mark.parametrize(
    ("sent", "stored"),
    [("#3F6FB5", "#3f6fb5"), ("#2A9D8FFF", "#2a9d8f")],
    ids=["a plain colour", "a colour with the picker's alpha byte"],
)
async def test_a_guild_can_choose_a_colour_instead(
    client: AsyncClient, acting_user, sent: str, stored: str
):
    """No artwork to find: the banner is a colour, and it costs no request.

    The shared colour picker emits ``#rrggbbaa``; a banner is a fill with
    nothing behind it, so the alpha is dropped rather than refused.
    """
    a = await acting_user(guild_role=CommunityRole.admin)

    response = await client.patch(
        f"/api/v1/communities/{a.guild.id}",
        headers=a.headers,
        json={"banner": _banner(color=sent)},
    )

    assert response.status_code == 200
    assert response.json()["banner"]["color"] == stored


async def test_a_null_banner_is_a_reset_not_a_removal(client: AsyncClient, acting_user):
    """A banner is never colourless and never without a layout, so there is
    nothing for null to clear — it puts the whole default back."""
    a = await acting_user(guild_role=CommunityRole.admin)
    await client.patch(
        f"/api/v1/communities/{a.guild.id}",
        headers=a.headers,
        json={"banner": _banner(color="#101010", text_align="left", fade="weak")},
    )

    response = await client.patch(
        f"/api/v1/communities/{a.guild.id}", headers=a.headers, json={"banner": None}
    )

    assert response.status_code == 200
    assert {
        key: value
        for key, value in response.json()["banner"].items()
        if key != "image_url"
    } == DEFAULT_BANNER


async def test_the_directory_carries_the_colour(
    client: AsyncClient, acting_user, session: AsyncSession, community_directory_on
):
    """A card with no artwork still has a banner, and it arrives in the payload
    that was already being sent."""
    a = await acting_user(guild_role=CommunityRole.admin)
    await client.patch(
        f"/api/v1/communities/{a.guild.id}",
        headers=a.headers,
        json={"banner": _banner(color="#2a9d8f")},
    )
    await _list_as_community(session, a.guild)
    stranger = await create_user(session, email="colourblind@example.com")

    response = await client.get(
        "/api/v1/communities/directory", headers=get_auth_headers(stranger)
    )

    card = next(g for g in response.json()["items"] if g["id"] == a.guild.id)
    assert card["banner"]["color"] == "#2a9d8f"
    assert card["banner"]["image_url"] is None


# --- the artwork entitlement --------------------------------------------------


async def test_a_guild_without_the_artwork_entitlement_cannot_upload(
    client: AsyncClient, acting_user, session: AsyncSession
):
    """The banner surface stays; the upload half of it does not. Every guild
    has a banner, so the colour is still there, and the icon is not gated: a
    guild without banner artwork still has a mark in the switcher. The
    entitlements read says so, for the settings page to offer the colour
    alone."""

    a = await acting_user(guild_role=CommunityRole.admin)
    await guild_administration(session, a.guild, banner_image_enabled=False)

    response = await client.put(
        f"/api/v1/communities/{a.guild.id}/banner",
        headers=a.headers,
        files=_banner_files(),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "BANNER_IMAGE_NOT_ENTITLED"

    colour = await client.patch(
        f"/api/v1/communities/{a.guild.id}",
        headers=a.headers,
        json={"banner": _banner(color="#8d5524")},
    )
    assert colour.status_code == 200
    assert colour.json()["banner"]["color"] == "#8d5524"
    assert (await _set_icon(client, a.guild.id, a.headers))["icon_url"] is not None

    entitlements = await client.get(
        f"/api/v1/communities/{a.guild.id}/entitlements", headers=a.headers
    )
    assert entitlements.json()["banner_image_enabled"] is False


async def test_a_guild_keeps_serving_artwork_it_already_had(
    client: AsyncClient, acting_user, session: AsyncSession
):
    """Losing the entitlement stops new uploads; it does not take down a
    banner the guild is already showing."""

    a = await acting_user(guild_role=CommunityRole.admin)
    payload = await _set_banner(client, a.guild.id, a.headers)
    await guild_administration(session, a.guild, banner_image_enabled=False)

    response = await client.get(payload["banner"]["image_url"], headers=a.headers)

    assert response.status_code == 200


# --- the icon -----------------------------------------------------------------


async def test_admin_sets_the_icon_and_gets_its_url_back(
    client: AsyncClient, acting_user
):
    """The guild list names it by URL and never carries its bytes."""
    a = await acting_user(guild_role=CommunityRole.admin)

    payload = await _set_icon(client, a.guild.id, a.headers)

    assert payload["icon_url"].startswith(f"/api/v1/communities/{a.guild.id}/image/")
    response = await client.get("/api/v1/communities/", headers=a.headers)
    entry = next(g for g in response.json() if g["id"] == a.guild.id)
    assert entry["icon_url"] == payload["icon_url"]
    assert "icon_base64" not in entry


async def test_the_icon_and_the_banner_do_not_disturb_each_other(
    client: AsyncClient, acting_user
):
    """Two pictures on one table, replaced independently."""
    a = await acting_user(guild_role=CommunityRole.admin)
    await _set_banner(client, a.guild.id, a.headers)

    payload = await _set_icon(client, a.guild.id, a.headers)

    assert payload["icon_url"] is not None
    assert payload["banner"]["image_url"] is not None

    cleared = await client.delete(
        f"/api/v1/communities/{a.guild.id}/icon", headers=a.headers
    )
    assert cleared.status_code == 200
    assert cleared.json()["icon_url"] is None
    assert cleared.json()["banner"]["image_url"] is not None


async def test_a_non_square_icon_is_refused(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin)

    response = await client.put(
        f"/api/v1/communities/{a.guild.id}/icon",
        headers=a.headers,
        files=_icon_files(icon=_png(256, 128)),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "IMAGE_WRONG_RATIO"


async def test_a_guild_admin_reads_their_own_entitlements(
    client: AsyncClient, acting_user
):
    """How the settings page knows to offer the colour alone."""
    a = await acting_user(guild_role=CommunityRole.admin)

    response = await client.get(
        f"/api/v1/communities/{a.guild.id}/entitlements", headers=a.headers
    )

    assert response.status_code == 200
    assert response.json() == {"community_id": a.guild.id, "banner_image_enabled": True}


async def test_a_member_does_not_read_entitlements(client: AsyncClient, acting_user):
    """Decisions made about a guild are its admins' business, not its roster's."""
    a = await acting_user(guild_role=CommunityRole.member)

    response = await client.get(
        f"/api/v1/communities/{a.guild.id}/entitlements", headers=a.headers
    )

    assert response.status_code == 403


async def test_a_truncated_image_is_a_bad_upload_not_a_fault(
    client: AsyncClient, acting_user
):
    """A file can carry a format's opening marks and stop before its
    dimensions. That is an answer about the upload, not an error."""
    a = await acting_user(guild_role=CommunityRole.admin)
    # PNG signature + IHDR marker and nothing after it.
    stub = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"

    response = await client.put(
        f"/api/v1/communities/{a.guild.id}/icon",
        headers=a.headers,
        files=_icon_files(icon=stub),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "IMAGE_INVALID"


async def test_dropping_below_the_seat_floor_stops_publishing_artwork(
    client: AsyncClient, acting_user, session: AsyncSession, community_directory_on
):
    """An operator can take a guild out of the directory without the guild
    doing anything, and what the listing published goes with it."""

    a = await acting_user(guild_role=CommunityRole.admin)
    await _set_icon(client, a.guild.id, a.headers)
    await _set_banner(client, a.guild.id, a.headers)
    await _list_as_community(session, a.guild)
    stranger = await create_user(session, email="seat-floor@example.com")
    headers = get_auth_headers(stranger)
    icon = await _variant_url(session, a.guild.id, GuildImageVariant.icon)
    card = await _card_url(session, a.guild.id)
    assert (await client.get(icon, headers=headers)).status_code == 200

    await guild_administration(session, a.guild, max_users=1)

    assert (await client.get(icon, headers=headers)).status_code == 404
    assert (await client.get(card, headers=headers)).status_code == 404
    # The directory it left agrees.
    directory = await client.get("/api/v1/communities/directory", headers=headers)
    assert all(g["id"] != a.guild.id for g in directory.json()["items"])


# --- how the banner is laid out -----------------------------------------------


async def test_an_admin_sets_the_alignment_and_the_fade(
    client: AsyncClient, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin)

    response = await client.patch(
        f"/api/v1/communities/{a.guild.id}",
        headers=a.headers,
        json={
            "banner": _banner(text_align="left", fade="strong", text_color="#000000")
        },
    )

    assert response.status_code == 200
    assert response.json()["banner"]["text_align"] == "left"
    assert response.json()["banner"]["fade"] == "strong"
    assert response.json()["banner"]["text_color"] == "#000000"


@pytest.mark.parametrize(
    "banner,status,detail",
    [
        (_banner(color="rebeccapurple"), 400, "BANNER_COLOR_INVALID"),
        # Readable over any fill or artwork only at one end of the scale.
        (_banner(text_color="#808080"), 400, "BANNER_TEXT_COLOR_INVALID"),
        # Read straight into a stylesheet, so the closed vocabulary is the
        # whole of what may be stored.
        (_banner(text_align="justify"), 422, None),
        (_banner(fade="extreme"), 422, None),
        # Replaced, not merged into: two of the four is not "leave the rest".
        ({"color": "#101010", "text_color": "#ffffff"}, 422, None),
    ],
)
async def test_a_banner_outside_what_one_may_be_is_refused(
    client: AsyncClient, acting_user, banner: dict, status: int, detail: str | None
):
    a = await acting_user(guild_role=CommunityRole.admin)

    response = await client.patch(
        f"/api/v1/communities/{a.guild.id}",
        headers=a.headers,
        json={"banner": banner},
    )

    assert response.status_code == status
    if detail is not None:
        assert response.json()["detail"] == detail


async def test_a_member_cannot_lay_out_the_banner(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin)
    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

    response = await client.patch(
        f"/api/v1/communities/{a.guild.id}",
        headers=b.headers,
        json={"banner": _banner(fade="strong")},
    )

    assert response.status_code == 403
