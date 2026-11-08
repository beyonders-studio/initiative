"""Unit tests for the reaction service's own logic — the summary shape and the
emoji rule. That every reactable kind has a resolver is a row in
``app/core/registry_coverage_test.py``."""

import pytest

from app.core.emoji import MAX_EMOJI_CODEPOINTS, validate_emoji
from app.core.reactions import ReactionTarget
from app.models.tenant.reaction import Reaction
from app.schemas.tenant.reaction import SUGGESTED_EMOJI
from app.services.tenant.reactions import (
    MAX_NAMED_REACTORS,
    summarize,
)

THUMBS = "\N{THUMBS UP SIGN}"
PARTY = "\N{PARTY POPPER}"


def _row(emoji: str, user_id: int) -> Reaction:
    return Reaction(
        target_type=ReactionTarget.comment.value,
        target_id=1,
        emoji=emoji,
        created_by=user_id,
    )


class TestSummarize:
    def test_groups_by_emoji_in_first_reacted_order(self):
        rows = [_row(PARTY, 1), _row(THUMBS, 2), _row(PARTY, 3)]
        groups = summarize(rows, viewer_id=None)
        assert [(g.emoji, g.count) for g in groups] == [(PARTY, 2), (THUMBS, 1)]

    def test_reacted_answers_for_the_viewer(self):
        rows = [_row(THUMBS, 7), _row(PARTY, 9)]
        groups = {g.emoji: g for g in summarize(rows, viewer_id=7)}
        assert groups[THUMBS].reacted is True
        assert groups[PARTY].reacted is False

    def test_anonymous_viewer_has_reacted_to_nothing(self):
        groups = summarize([_row(THUMBS, 7)], viewer_id=None)
        assert groups[0].reacted is False

    def test_named_reactors_are_capped_but_the_count_is_not(self):
        # ``reactor`` is unloaded on these detached rows, so no name is added;
        # what matters is that the count still tells the whole truth.
        rows = [_row(THUMBS, uid) for uid in range(MAX_NAMED_REACTORS + 5)]
        [group] = summarize(rows, viewer_id=None)
        assert group.count == MAX_NAMED_REACTORS + 5
        assert len(group.users) <= MAX_NAMED_REACTORS


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
