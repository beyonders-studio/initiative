"""The account's use of the per-user signal channel.

The signed-in account is read once, when a tab boots, and then only when
something asks for it again. Most of what it holds cannot change underneath
that — but some of it can, and not always by anything its owner did: somebody
is added to a community by an admin or a group sync, a community lists itself,
a platform role is granted. From that moment the tab is deciding on an answer
that is no longer true, and would go on doing so until it next loaded.

This is the poke that fixes it. Like every frame here it carries **nothing**:
it says "your account changed", the client re-reads ``GET /me``, and that
request — authorized by being that account — is the only place anything is
decided. Nothing about what changed crosses the wire, so a frame delivered to
the wrong socket would tell its reader nothing they could not already ask for
themselves.

The socket, the after-commit queueing and the cross-worker bus belong to
:mod:`app.services.platform.user_stream`, shared with the inbox channel.
"""

from typing import Any

from app.db import post_commit
from app.services.platform import user_stream

#: What the client switches on to tell this channel from the inbox one.
RESOURCE = "account"


def queue_signal_to_everyone(session: Any, action: str = "changed") -> None:
    """Note that this session changed what ``/me`` would answer for every
    account, such as a deployment rule it reads. Sent once the transaction
    commits; every connected reader refetches once."""
    frame = user_stream.build_frame(RESOURCE, action)
    post_commit.after_commit(
        session,
        lambda: user_stream.publish_to_everyone(frame),
        key=("account_signal_to_everyone", action),
    )


def queue_account_signal(
    session: Any, user_id: int | None, action: str = "changed"
) -> None:
    """Note that this session changed what ``/me`` would answer.

    Sent once the transaction commits, never before: a frame that arrives ahead
    of the COMMIT hands the client the state it is replacing, and nothing polls
    behind it closely enough to correct that.
    """
    user_stream.queue_frame(session, user_id, user_stream.build_frame(RESOURCE, action))
