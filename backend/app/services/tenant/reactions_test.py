"""The emoji rule a reaction is held to. That every reactable kind has a
resolver is a row in ``app/core/registry_coverage_test.py``."""

import pytest

from app.core.emoji import MAX_EMOJI_CODEPOINTS, validate_emoji
from app.schemas.tenant.reaction import SUGGESTED_EMOJI


class TestEmojiRule:
    @pytest.mark.parametrize("emoji", list(SUGGESTED_EMOJI))
    def test_every_suggested_emoji_validates(self, emoji):
        assert validate_emoji(emoji) == emoji

    @pytest.mark.parametrize(
        "emoji",
        [
            "\N{THUMBS UP SIGN}\N{EMOJI MODIFIER FITZPATRICK TYPE-4}",  # skin tone
            (
                "\N{REGIONAL INDICATOR SYMBOL LETTER U}"
                "\N{REGIONAL INDICATOR SYMBOL LETTER S}"
            ),  # flag
            "1\N{VARIATION SELECTOR-16}\N{COMBINING ENCLOSING KEYCAP}",  # keycap
        ],
    )
    def test_accepts_real_emoji_sequences(self, emoji):
        assert validate_emoji(emoji) == emoji

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "   ",
            "lgtm",
            "<img src=x onerror=1>",
            "\N{THUMBS UP SIGN} nice",
            "a\N{THUMBS UP SIGN}",
            "\N{THUMBS UP SIGN}" * (MAX_EMOJI_CODEPOINTS + 1),
        ],
    )
    def test_refuses_anything_that_would_render_as_text(self, value):
        with pytest.raises(ValueError):
            validate_emoji(value)
