"""Unit tests for the guards on the user schemas."""

import pytest
from pydantic import ValidationError

from app.schemas.platform.user import (
    ProfileDecorations,
    UserCommunityRead,
    UserSelfUpdate,
)


def test_self_update_accepts_an_external_avatar_url() -> None:
    model = UserSelfUpdate(avatar_url="https://idp.example/pic.png")

    assert model.avatar_url == "https://idp.example/pic.png"
    assert UserSelfUpdate(avatar_url=None).avatar_url is None


def test_the_guild_read_of_an_account_carries_no_name() -> None:
    """``UserCommunityRead`` is a handle and a standing, and stops there.

    The membership surfaces read an account back to say what it is now. None of
    the account's own business travels with the answer, and neither does the
    person's name: this shape draws nobody, so the field is not declared.
    """
    for absent in ("display_name", "email", "role"):
        assert absent not in UserCommunityRead.model_fields


@pytest.mark.always
def test_no_guild_content_reads_a_person_from_the_users_table() -> None:
    """Why none of those shapes needs a rule of its own about names.

    Guild content reaches a person through ``guild_member_profiles``, which
    carries ``display_name``, the name the member set in that guild. A
    relationship pointing at ``users`` instead would reach the account, which
    has no such name and no business in a guild's payload.
    """
    import pathlib as _pathlib
    import re as _re

    models = _pathlib.Path(__file__).resolve().parents[1] / "models" / "tenant"
    offenders = []
    for path in models.glob("*.py"):
        for match in _re.finditer(
            r'^\s*(\w+):\s*(?:Optional\[|List\[)?"User"\]?\s*=\s*Relationship',
            path.read_text(),
            _re.MULTILINE,
        ):
            offenders.append(f"{path.name}: {match.group(1)}")
    assert not offenders, (
        "guild content reaching a person off the users table rather than the "
        f"guild projection: {offenders}"
    )


@pytest.mark.parametrize(
    ("worn", "kept"),
    [
        # The year is the wearer's, not the clock's: stored as given.
        ({"banner": "education.gradbanner"}, 2014),
        ({"trophies": ["education.gradtrophy"]}, 2014),
        # A value nothing would draw is not state worth keeping.
        ({"banner": "core.aurora"}, None),
    ],
)
def test_a_year_is_kept_only_on_a_decoration_that_carries_one(worn, kept) -> None:
    assert ProfileDecorations(**worn, grad_year=2014).grad_year == kept


def test_a_year_outside_the_range_is_refused() -> None:
    with pytest.raises(ValidationError):
        ProfileDecorations(trophies=["education.gradtrophy"], grad_year=1492)
