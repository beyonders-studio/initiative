"""Which origins a served document may frame.

The property under test is that the answer is a property of the **deployment**:
the origins of the live plug-in services an operator has wired up. So the same
header goes to every document, it names no guild, install or reader, and an
operator's kill switch — on the registration or on its publisher — is the thing
that takes an origin back out of it.
"""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.embed_csp import plugin_frame_policy
from app.core.config import settings
from app.models.platform.publisher import Publisher
from app.services.marketplace import registration_lookup
from app.services.marketplace.registration_lookup import (
    frame_origins,
    invalidate_registrations,
)
from app.testing import create_plugin_service_registration, create_publisher

FRAMED = "https://framed.example.test"
SECOND = "https://second.example.test"


class TestTheRegisteredOrigins:
    async def test_a_live_registration_is_named(self, session: AsyncSession):
        await create_plugin_service_registration(
            session,
            public_id="tests.framed",
            base_url=FRAMED,
            allowed_origins=[FRAMED],
        )

        assert FRAMED in await frame_origins()

    async def test_every_live_registration_is_named_once_and_in_order(
        self, session: AsyncSession
    ):
        """Two plug-ins served from one origin put it on the list once. The order
        is the sorted one, so the header is the same string until a
        registration changes rather than varying with row order."""
        await create_plugin_service_registration(
            session,
            public_id="tests.first",
            base_url=FRAMED,
            allowed_origins=[FRAMED, SECOND],
        )
        await create_plugin_service_registration(
            session,
            public_id="tests.second",
            base_url=SECOND,
            allowed_origins=[SECOND],
        )

        origins = await frame_origins()
        assert FRAMED in origins
        assert origins.count(SECOND) == 1
        assert list(origins) == sorted(origins)

    async def test_a_stopped_registration_is_not_named(self, session: AsyncSession):
        """The kill switch reaches the header: a stopped plug-in is not framed
        while it is stopped."""
        registration = await create_plugin_service_registration(
            session,
            public_id="tests.stopped",
            base_url=FRAMED,
            allowed_origins=[FRAMED],
        )

        registration.enabled = False
        session.add(registration)
        await session.commit()
        invalidate_registrations()

        assert FRAMED not in await frame_origins()

    async def test_a_registration_whose_publisher_is_off_is_not_named(
        self, session: AsyncSession
    ):
        """A publisher's switch reaches the header for every plug-in under it."""
        await create_plugin_service_registration(
            session,
            public_id="offpub.framed",
            base_url=FRAMED,
            allowed_origins=[FRAMED],
        )
        publisher: Publisher = await create_publisher(session, prefix="offpub")
        publisher.enabled = False
        session.add(publisher)
        await session.commit()
        invalidate_registrations()

        assert FRAMED not in await frame_origins()

    async def test_a_registration_with_no_keys_is_not_named(
        self, session: AsyncSession
    ):
        """No key set, not live, not framed."""
        await create_plugin_service_registration(
            session,
            public_id="tests.keyless",
            base_url=FRAMED,
            allowed_origins=[FRAMED],
            jwks={},
        )

        assert FRAMED not in await frame_origins()


class TestThePolicy:
    async def test_a_document_may_frame_a_registered_plugin(
        self, session: AsyncSession
    ):
        await create_plugin_service_registration(
            session,
            public_id="tests.framed",
            base_url=FRAMED,
            allowed_origins=[FRAMED],
        )

        assert FRAMED in _directive(await plugin_frame_policy(), "frame-src")

    async def test_a_deployment_with_nothing_live_frames_nothing(
        self, session: AsyncSession
    ):
        """Nothing live, nothing named: the document carries the same policy
        the middleware puts on everything else."""
        registration = await create_plugin_service_registration(
            session,
            public_id="tests.stopped",
            base_url=FRAMED,
            allowed_origins=[FRAMED],
        )
        registration.enabled = False
        session.add(registration)
        await session.commit()
        invalidate_registrations()

        assert await plugin_frame_policy() == _ordinary_policy()

    async def test_an_unreadable_list_leaves_the_ordinary_policy(self, monkeypatch):
        """Answered, not raised: this runs on the route that serves every
        document, so the fallback is the stricter policy and the page still
        loads."""

        async def boom() -> tuple[str, ...]:
            raise RuntimeError("no")

        monkeypatch.setattr(registration_lookup, "frame_origins", boom)

        assert await plugin_frame_policy() == _ordinary_policy()


def test_the_ordinary_policy_frames_no_plugin():
    """What the middleware puts on every response that is not a document."""
    assert "example.test" not in _directive(_ordinary_policy(), "frame-src")


def _ordinary_policy() -> str:
    """The app-wide policy, framing no plug-in."""
    return settings.content_security_policy_with_frames(
        (), captcha_provider=settings.CAPTCHA_PROVIDER
    )


def _directive(policy: str, name: str) -> str:
    for directive in policy.split(";"):
        cleaned = directive.strip()
        if cleaned.startswith(f"{name} "):
            return cleaned
    raise AssertionError(f"{name} missing from {policy!r}")
