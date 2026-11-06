"""The direct-message channel on the per-user signal socket.

The third channel over the shared transport, built like
:mod:`app.services.platform.account_stream`. Frames carry **nothing** — not a
conversation id, not a sender, not a count. A tab that receives one fetches its
queue through the ordinary authorized endpoint and decrypts locally, so that
request is the only place anything is decided and a frame delivered to the wrong
socket would tell its reader nothing.

A separate channel rather than an arm on ``connections``: a connections frame means
"re-read three permission lists", and a mailbox poll should not ride behind it.
"""

from app.services.platform import user_stream

#: What the client switches on to tell this channel from the others.
RESOURCE = "dm"


async def signal_dm(user_id: int, action: str = "changed") -> None:
    """Tell one account's open tabs there is something to collect."""
    await user_stream.publish([user_id], user_stream.build_frame(RESOURCE, action))
