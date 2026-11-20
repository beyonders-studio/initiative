"""What a user agent is shown as in the account's own session list."""

import pytest

from app.core.user_agents import ClientKind, describe, kind_of

CHROME_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
SAFARI_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)
EDGE_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0"
)
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"


@pytest.mark.parametrize(
    ("agent", "expected"),
    [
        (CHROME_MAC, "Chrome on macOS"),
        (SAFARI_IPHONE, "Safari on iPhone"),
        (FIREFOX_LINUX, "Firefox on Linux"),
        # Derivatives carry ``Chrome`` too; the marker order keeps them apart.
        (EDGE_WINDOWS, "Edge on Windows"),
        # Android says ``Linux`` too.
        ("Mozilla/5.0 (Linux; Android 14; Pixel 8) Chrome/140.0", "Chrome on Android"),
        # Nothing to read is nothing rather than a guess.
        (None, None),
        ("", None),
        ("   ", None),
        # An unfamiliar agent keeps itself.
        ("curl/8.7.1", "curl/8.7.1"),
    ],
)
def test_a_browser_reads_as_itself_and_its_platform(agent, expected):
    assert describe(agent) == expected


@pytest.mark.parametrize(
    ("agent", "expected"),
    [
        (CHROME_MAC, ClientKind.desktop),
        (EDGE_WINDOWS, ClientKind.desktop),
        (FIREFOX_LINUX, ClientKind.desktop),
        (SAFARI_IPHONE, ClientKind.mobile),
        ("Mozilla/5.0 (Linux; Android 14; Pixel 8) Chrome/140.0", ClientKind.mobile),
        (None, ClientKind.unknown),
        ("curl/8.7.1", ClientKind.unknown),
    ],
)
def test_which_picture_to_draw(agent, expected):
    assert kind_of(agent) is expected


def test_an_unfamiliar_agent_is_cut_to_a_length():
    """Cut so one long header cannot stretch the row it is drawn in."""
    assert len(describe("x" * 500) or "") == 60
