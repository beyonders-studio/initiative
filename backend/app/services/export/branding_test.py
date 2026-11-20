"""Which guild icons a PDF report's header stages."""

from app.services.export.branding import icon_asset


def test_icon_asset_names_the_file_by_its_type():
    assert icon_asset("image/png", b"\x89PNG-ish") == ("guild-icon.png", b"\x89PNG-ish")
    # jpeg maps to a .jpg extension.
    jpeg = icon_asset("image/jpeg", b"\xff\xd8jpeg-ish")
    assert jpeg is not None and jpeg[0] == "guild-icon.jpg"


def test_icon_asset_rejects_non_raster():
    # SVG is deliberately excluded (vector parser surface in the trusted report).
    assert icon_asset("image/svg+xml", b"<svg></svg>") is None
    assert icon_asset("text/html", b"<h1>x</h1>") is None
    assert icon_asset(None, b"anything") is None


def test_icon_asset_rejects_empty_and_oversized():
    from app.services.export import branding

    assert icon_asset("image/png", b"") is None
    assert icon_asset("image/png", None) is None
    assert icon_asset("image/png", b"x" * (branding._MAX_ICON_BYTES + 1)) is None
