import pytest

from app.core.email_masking import mask_email


@pytest.mark.parametrize(
    "raw,masked",
    [
        # The canonical shape: both halves keep their first and last character.
        ("user1@example.com", "u***1@e***m"),
        ("jordan@example.com", "j***n@e***m"),
        # Multi-label domains collapse whole, dots included — the mask says
        # nothing about how many labels there were.
        ("foo@mail.example.co.uk", "f***o@m***k"),
        # A single-character half has no distinct last character to keep.
        ("a@example.com", "a***@e***m"),
        ("jordan@x", "j***n@x***"),
        ("a@b", "a***@b***"),
        # Two characters: first and last are both real and both kept.
        ("ab@cd.e", "a***b@c***e"),
        # Display-only: case is kept, surrounding whitespace is not.
        ("Jordan@Example.COM", "J***n@E***M"),
        ("  user1@example.com  ", "u***1@e***m"),
    ],
)
def test_masks_both_halves(raw: str, masked: str) -> None:
    assert mask_email(raw) == masked


@pytest.mark.parametrize("empty", [None, ""])
def test_passes_through_unset_addresses(empty) -> None:
    """An address that was never set stays falsy, so callers can branch on it."""
    assert mask_email(empty) == empty


@pytest.mark.parametrize(
    "malformed",
    ["not-an-email", "@example.com", "user1@", "   ", "@"],
)
def test_masks_anything_that_does_not_parse(malformed: str) -> None:
    """Never echo back a value we couldn't parse — it may still be an address."""
    assert mask_email(malformed) == "***"
