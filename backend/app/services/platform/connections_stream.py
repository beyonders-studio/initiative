"""Connections, requests and the ignore list, on the per-user signal channel.

The third channel over the shared transport, beside the inbox
(:mod:`app.services.platform.notification_stream`) and the account
(:mod:`app.services.platform.account_stream`). A frame carries **nothing**: it
says one of these lists moved, the client re-reads through the ordinary
endpoints, and those requests — own-row, or answered by
``public.dm_apparent_permission`` — are where anything is decided.

Its own channel rather than an arm on the account one, because an ``account``
frame means "re-read ``GET /me``", and a membership change would
otherwise drag a refetch of three connection lists behind it.

**Being ignored sends nothing.** The account that was ignored is signalled
neither when it happens, nor when it is lifted, nor for a request of theirs
that is filed where nobody will see it. A frame is as much a tell as a
notification, so where a real event coincides with an ignore — a request from
somebody the recipient ignores — only the requester is signalled, and each
frame carries exactly the state its reader may know about.
"""

from typing import Any

from app.services.platform import user_stream

#: What the client switches on to tell this channel from the other two.
RESOURCE = "connections"


def queue_connections_signal(
    session: Any, user_id: int | None, action: str = "changed"
) -> None:
    """Note that this session changed what those lists would answer.

    Sent once the transaction commits, never before: a frame that arrives ahead
    of the COMMIT hands the client the state it is replacing.
    """
    user_stream.queue_frame(session, user_id, user_stream.build_frame(RESOURCE, action))
