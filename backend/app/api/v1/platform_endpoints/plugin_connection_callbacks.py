"""Where a vendor returns a person during a plug-in connection's flow.

Two addresses an operator registers with each vendor client, the same for
every plug-in on this deployment:

* ``GET /plugin-connections/callback`` — the OAuth redirect: ``state`` and
  ``code`` (or ``error``).
* ``GET /plugin-connections/setup`` — an installation-style vendor's return from
  its install page: ``state``, ``installation_id`` and ``setup_action``.

What they act on is named by ``state``, which Initiative sealed when the flow
started (:mod:`app.services.tenant.connection_flow_state`). Each also reads the
person from Initiative's own session cookie, checked as every signed-in request
is (an active account, a live session), and goes on only when that person is
the one who started the flow; a community connection also needs them to still
hold its seat. The work runs on the system engine routed into the community the
state names. Each answers with a redirect: onward to the vendor, or to the
landing page with how the flow ended.

Not part of the OpenAPI document: only a vendor sends a browser here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.api.deps import (
    CREDENTIAL_SESSION,
    SessionDep,
    get_current_active_user,
    get_current_user,
)
from app.core.identify import presented_credential
from app.core.rate_limit import limiter
from app.services.tenant import plugin_connection_flows as flows_service

router = APIRouter(include_in_schema=False)


async def signed_in_person(request: Request, session: SessionDep) -> int | None:
    """The person signed in to Initiative in this browser, or ``None``.

    Read from the session cookie alone, and held to what every signed-in
    request is: a valid session for an active account.
    """
    presented = presented_credential(request)
    if presented is None or presented.bearer:
        return None
    try:
        user = await get_current_user(request, session)
        user = await get_current_active_user(request, session, user)
    except HTTPException:
        return None
    if getattr(request.state, "credential", None) != CREDENTIAL_SESSION:
        return None
    return user.id


SignedInDep = Annotated[int | None, Depends(signed_in_person)]


def _redirect(url: str) -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/setup")
@limiter.limit("30/minute")
async def connection_setup(
    request: Request,
    signed_in: SignedInDep,
    state: str | None = Query(default=None, max_length=4096),
    installation_id: str | None = Query(default=None, max_length=64),
    setup_action: str | None = Query(default=None, max_length=32),
) -> RedirectResponse:
    """The vendor's install page is done: go on to authorize, or say the
    install is waiting on somebody's approval."""
    return _redirect(
        await flows_service.complete_setup(
            state_token=state,
            installation_id=installation_id,
            setup_action=setup_action,
            signed_in=signed_in,
        )
    )


@router.get("/callback")
@limiter.limit("30/minute")
async def connection_callback(
    request: Request,
    signed_in: SignedInDep,
    state: str | None = Query(default=None, max_length=4096),
    code: str | None = Query(default=None, max_length=2048),
    error: str | None = Query(default=None, max_length=200),
) -> RedirectResponse:
    """The vendor's answer to the authorization request: exchange the code,
    store the connection, and land the person on how it went."""
    return _redirect(
        await flows_service.complete_callback(
            state_token=state, code=code, error=error, signed_in=signed_in
        )
    )
