"""What an installed plug-in sends to call another plug-in through Initiative."""

from typing import Any

from pydantic import ConfigDict

from app.schemas.base import SanitizedBaseModel

__all__ = ["PluginHubCall"]


class PluginHubCall(SanitizedBaseModel):
    """One call's parameters, checked against the ones the endpoint declares
    and passed on as they are."""

    model_config = ConfigDict(extra="forbid")

    params: dict[str, Any] = {}
