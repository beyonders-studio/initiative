"""A file sent in pieces over the resumable-upload routes, for a test that
then hands the upload to the endpoint it is for."""

from __future__ import annotations

import base64

from httpx import AsyncClient

TUS = {"Tus-Resumable": "1.0.0"}


def upload_metadata(**values: str) -> str:
    """``Upload-Metadata``: each value base64-encoded after its key."""
    return ",".join(
        f"{key} {base64.b64encode(value.encode()).decode()}"
        for key, value in values.items()
    )


async def send_in_pieces(
    client: AsyncClient, actor, body: bytes, **metadata: str
) -> str:
    """Create an upload of ``body`` described by ``metadata`` (``purpose``,
    ``filename`` and what it is for) and send it whole; its id."""
    created = await client.post(
        actor.g("/resumable-uploads"),
        headers={
            **actor.headers,
            **TUS,
            "Upload-Length": str(len(body)),
            "Upload-Metadata": upload_metadata(**metadata),
        },
    )
    assert created.status_code == 201, created.text
    location = created.headers["location"]
    path = location[location.index("/api/") :]
    sent = await client.patch(
        path,
        headers={
            **actor.headers,
            **TUS,
            "Upload-Offset": "0",
            "Content-Type": "application/offset+octet-stream",
        },
        content=body,
    )
    assert sent.status_code == 204, sent.text
    return path.rsplit("/", 1)[1]
