"""Home layouts as the marketplace offers them to a person."""

from typing import Any

from pydantic import ConfigDict

from app.schemas.base import SanitizedBaseModel


class HomeLayoutGrid(SanitizedBaseModel):
    """Where a widget sits on the twelve-column home grid, in columns and rows."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    x: int
    y: int
    w: int
    h: int


class HomeLayoutWidget(SanitizedBaseModel):
    """One widget a layout places. ``options`` are the few that mean the same on
    anybody's page — how far ahead, which tools, clock or timer."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    type: str
    grid: HomeLayoutGrid
    options: dict[str, Any] | None = None


class HomeLayoutListing(SanitizedBaseModel):
    """A home layout somebody can add to their home page as a new view.

    A marketplace listing, so the words are its publisher's; ``uid`` names it on
    every deployment carrying the catalog.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    uid: str
    public_id: str
    name: str
    publisher: str
    description: str
    long_description: str | None = None
    avatar_url: str | None = None
    version: str
    widgets: list[HomeLayoutWidget]


class HomeLayoutListResponse(SanitizedBaseModel):
    """Every home layout this deployment offers. Read all at once — one shelf."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[HomeLayoutListing]
