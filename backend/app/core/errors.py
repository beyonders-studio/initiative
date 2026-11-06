"""The refusal a service raises with a message code and the status it answers."""

from collections.abc import Mapping


class CodedError(Exception):
    """A refusal carrying a ``messages.py`` code and its HTTP status.

    Services raise it rather than ``HTTPException`` so they stay callable from a
    job or a worker; ``app.main`` answers any that reaches the API with
    :attr:`body` at ``status_code``. A subclass sets its own default status as a
    class attribute.

    ``params`` are the values the code's wording is filled in with — which
    kind of thing was not found, say — so one code serves every kind rather
    than each kind spelling its own.
    """

    status_code: int = 400

    def __init__(
        self,
        code: str,
        status_code: int | None = None,
        *,
        params: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.params = dict(params) if params else None
        if status_code is not None:
            self.status_code = status_code

    @property
    def body(self) -> dict:
        """The response body: ``{"detail": code}``, with ``params`` when set."""
        if self.params:
            return {"detail": self.code, "params": self.params}
        return {"detail": self.code}


class PluginChannelError(CodedError):
    """A refusal on the plug-in channel, as a message code plus its HTTP answer."""
