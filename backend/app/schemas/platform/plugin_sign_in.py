"""Wire shapes of Sign in with Initiative's own page.

The authorize page is the SPA's: it reads the request a plug-in sent somebody
with, asks where they may open the plug-in, and sends them back with a code.
See :mod:`app.services.marketplace.plugin_sign_in`.
"""

from pydantic import BaseModel, Field

#: The longest value of any authorize parameter.
_PARAM_MAX = 2048


class PluginSignInRequest(BaseModel):
    """The authorize request, as the plug-in sent it."""

    client_id: str | None = Field(default=None, max_length=_PARAM_MAX)
    redirect_uri: str | None = Field(default=None, max_length=_PARAM_MAX)
    response_type: str | None = Field(default=None, max_length=_PARAM_MAX)
    scope: str | None = Field(default=None, max_length=_PARAM_MAX)
    state: str | None = Field(default=None, max_length=_PARAM_MAX)
    nonce: str | None = Field(default=None, max_length=_PARAM_MAX)
    code_challenge: str | None = Field(default=None, max_length=_PARAM_MAX)
    code_challenge_method: str | None = Field(default=None, max_length=_PARAM_MAX)


class PluginSignInClientRead(BaseModel):
    """The plug-in asking, once its client and return address check out."""

    name: str
    #: The listing, for adding the plug-in to a community from the marketplace.
    listing_public_id: str
    #: Set when the request itself is malformed: send the person straight back.
    refusal_redirect: str | None = None
    #: Where the person goes if they decline.
    cancel_redirect: str


class PluginSignInPlaceRead(BaseModel):
    """Somewhere the person may open the plug-in."""

    community_id: int
    community_name: str
    initiative_id: int | None = None
    initiative_name: str | None = None


class PluginSignInPlacesRead(BaseModel):
    places: list[PluginSignInPlaceRead]
    #: Every community of the person's holding the plug-in, whether or not it
    #: admits them, so the page offers to add it only where it is missing.
    installed_community_ids: list[int]


class PluginSignInAuthorize(PluginSignInRequest):
    """The request, and the place the person chose."""

    community_id: int = Field(gt=0)
    initiative_id: int | None = Field(default=None, gt=0)


class PluginSignInRedirect(BaseModel):
    """Where to send the person: back to the plug-in, with a code."""

    redirect_to: str
