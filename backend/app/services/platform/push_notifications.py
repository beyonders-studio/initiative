import asyncio
import json
import logging
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, AsyncContextManager, Dict, Optional, Sequence

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.notification import NotificationType
from app.models.platform.push_token import PushToken
from app.services.platform import push_tokens

from app.services.platform import push_config, push_relay, user_notifications
from app.services.platform.push_config import ResolvedPushConfig

logger = logging.getLogger(__name__)

# FCM API endpoint
FCM_API_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

# OAuth2 scopes required for FCM
FCM_SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]

# Android notification channel a given notification type is delivered on. The
# channel is what the user sees (and can mute) in the OS notification settings,
# so related types share one rather than getting a row each.
#
# These ids must exist in the installed app — see NotificationChannelManager in
# frontend/android, which registers exactly this set. A type absent here (the
# in-app-only ones, which never push) falls back to the general channel; adding
# a NEW channel id means a native release, so prefer an existing one.
DEFAULT_CHANNEL = "default"
PUSH_CHANNELS: dict[NotificationType, str] = {
    NotificationType.task_assignment: "task_assignment",
    NotificationType.overdue_tasks: "overdue_tasks",
    NotificationType.initiative_added: "initiative_added",
    # Join requests are initiative-membership news, so they ride the channel the
    # installed app already registers for it rather than asking for a new one
    # (a new channel id would mean a native release).
    NotificationType.initiative_join_requested: "initiative_added",
    NotificationType.initiative_join_approved: "initiative_added",
    NotificationType.initiative_join_denied: "initiative_added",
    NotificationType.project_added: "project_added",
    NotificationType.mention: "mention",
    NotificationType.comment_on_task: "comments",
    NotificationType.comment_on_resource: "comments",
    # Rides the comments channel: a channel of its own would need a new app.
    NotificationType.subscription_activity: "comments",
    NotificationType.assigned_activity: "comments",
    NotificationType.comment_reply: "comments",
    NotificationType.direct_message: "messages",
    # Somebody asking to reach you, and the answer when you asked. Messaging
    # news, so it rides the channel the installed app already registers for
    # messages rather than asking for a new one — same reasoning as the join
    # requests above: a new channel id would mean a native release.
    NotificationType.message_request_received: "messages",
    NotificationType.message_request_accepted: "messages",
    NotificationType.connection_requested: "messages",
    NotificationType.connection_accepted: "messages",
    # Its own channel rather than one of the above. A post is a category of
    # its own — nothing already here describes it, and filing it under
    # initiative news would mean muting one to mute the other. A channel is
    # what the Android app offers a user to mute, so this is what it costs.
    NotificationType.post_published: "posts",
    # A reaction is comment news, so it rides the channel the installed app
    # already registers for comments — same reasoning as the join requests
    # above: a new channel id would mean a native release.
    NotificationType.comment_reaction: "comments",
    NotificationType.event_invitation: "calendar_events",
    NotificationType.event_cancelled: "calendar_events",
    NotificationType.event_rsvp: "calendar_events",
    NotificationType.event_reminder: "event_reminder",
    NotificationType.access_grant_requested: "access_grants",
    NotificationType.access_grant_approved: "access_grants",
    NotificationType.access_grant_denied: "access_grants",
    NotificationType.access_grant_revoked: "access_grants",
    # Mostly a reply on something the reader wrote, so it rides the comments
    # channel the installed app already registers rather than asking for a
    # new one — a new channel id would mean a native release.
    NotificationType.ticket_updated: "comments",
    NotificationType.moderation_removal: "comments",
    NotificationType.moderation_warning: "comments",
    # Work landing on a person, so the channel task assignments use.
    NotificationType.case_opened: "task_assignment",
    NotificationType.case_replied: "task_assignment",
}


def channel_for(notification_type: Optional[NotificationType]) -> str:
    """Android channel id for a notification type."""
    if notification_type is None:
        return DEFAULT_CHANNEL
    return PUSH_CHANNELS.get(notification_type, DEFAULT_CHANNEL)


#: The service-account credential and the JSON it was built from. Google
#: access tokens last an hour, so one credential serves every push until it
#: nears expiry or the configured account changes.
_credentials: tuple[str, service_account.Credentials] | None = None
#: One refresh at a time; deliveries that queued behind it reuse its token.
_refresh_lock = asyncio.Lock()


async def _get_fcm_access_token(cfg: ResolvedPushConfig) -> Optional[str]:
    """An OAuth2 access token for the configured service account.

    Returns None if FCM is not configured or credentials are invalid.

    ``cfg`` is passed in rather than read here: the credential lives on
    ``app_setting_secrets``, which only the system engine may read, so it is
    resolved by ``push_config`` on a session of its own. The token is reused
    while it is valid; a refresh is a blocking HTTP call, so it runs on a
    worker thread.
    """
    global _credentials
    if not cfg.enabled or not cfg.service_account_json:
        return None

    try:
        if _credentials is None or _credentials[0] != cfg.service_account_json:
            _credentials = (
                cfg.service_account_json,
                service_account.Credentials.from_service_account_info(
                    json.loads(cfg.service_account_json), scopes=FCM_SCOPES
                ),
            )
        credentials = _credentials[1]
        if not credentials.valid:
            async with _refresh_lock:
                if not credentials.valid:
                    await asyncio.to_thread(credentials.refresh, Request())
        return credentials.token
    except Exception:
        logger.exception("Failed to get FCM access token")
        return None


async def send_push_notification(
    client: httpx.AsyncClient,
    *,
    push_token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    channel_id: Optional[str] = None,
    platform: str = "android",
    badge: Optional[int] = None,
) -> tuple[bool, bool]:
    """Send a push notification to one device with FCM's HTTP v1 API.

    The message goes to FCM itself, signed with the service account, or to the
    push relay, which takes the same request with this server's relay key.
    iPhone tokens always go to the relay; Android tokens go to it only when
    no service account is configured.

    A token sent through the relay is the handle the relay gave the device
    (``push_relay.is_handle``), and one sent to FCM is the device's own. A
    token of the other kind cannot be delivered where this platform now goes
    (the operator added or removed a service account after the device
    registered), so it is reported dead without a request; the app registers
    the right kind on its next launch.

    Args:
        client: The HTTP client the whole fan-out shares
        push_token: The device's relay handle, or its FCM token when Android
            goes to FCM directly
        title: Notification title
        body: Notification body
        data: Optional data payload (must be string key-value pairs)
        channel_id: Android notification channel to deliver on
        platform: The device's platform, ``android`` or ``ios``
        badge: The number an iPhone puts on the app icon. An Android launcher
            counts the notifications in the tray instead, one each.

    Returns:
        Tuple of (success, should_delete_token):
        - success: True if notification was sent successfully
        - should_delete_token: True if token is invalid and should be deleted

    Error handling:
        - 404/410: Token invalid, should be deleted from database
        - 401: Credentials issue, logged as error (the relay key is dropped,
          so the next push registers again)
        - 5xx: Server error, logged as warning
        - Network errors: Logged as warning
    """
    cfg = await push_config.ensure_push_config_fresh()
    if not cfg.enabled:
        logger.warning("FCM not enabled, skipping push notification")
        return (False, False)

    via_relay = platform == "ios" or not cfg.service_account_json
    if push_relay.is_handle(push_token) != via_relay:
        logger.info(
            "Push token for %s is not addressable %s; dropping it",
            platform,
            "through the push relay" if via_relay else "through FCM",
        )
        return (False, True)
    relay_server_id: Optional[str] = None
    if via_relay:
        held = await push_relay.credentials(client)
        if held is None:
            logger.error("Push relay credentials unavailable")
            return (False, False)
        relay_server_id, relay_key = held
        url = push_relay.send_url(cfg.project_id)
        headers = {
            "Authorization": push_relay.authorization(relay_server_id, relay_key),
            "Content-Type": "application/json",
        }
    else:
        if not cfg.project_id:
            logger.warning("FCM project id not set, skipping push notification")
            return (False, False)
        access_token = await _get_fcm_access_token(cfg)
        if not access_token:
            logger.error("Failed to get FCM access token")
            return (False, False)
        url = FCM_API_URL.format(project_id=cfg.project_id)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    # Build FCM message
    fcm_message: dict[str, Any] = {
        "token": push_token,
        "notification": {
            "title": title,
            "body": body,
        },
    }
    message = {"message": fcm_message}

    # Add Android-specific configuration for notification channels
    if channel_id:
        fcm_message["android"] = {
            "notification": {
                "channel_id": channel_id,
            }
        }

    if badge is not None and platform == "ios":
        fcm_message["apns"] = {"payload": {"aps": {"badge": badge}}}

    # Add data payload if provided (convert all values to strings)
    if data:
        fcm_message["data"] = {k: str(v) for k, v in data.items()}

    service = "Push relay" if via_relay else "FCM"
    try:
        response = await client.post(url, json=message, headers=headers)

        if response.status_code == 200:
            logger.info("Push notification sent through %s", service)
            return (True, False)
        elif response.status_code in (404, 410):
            # Token invalid or unregistered - should be deleted
            logger.warning(
                "%s token invalid (status %s)", service, response.status_code
            )
            return (False, True)
        elif response.status_code == 401:
            # Credentials issue - don't delete token
            logger.error(
                "%s authentication failed (status %s, %s byte answer)",
                service,
                response.status_code,
                len(response.content),
            )
            if relay_server_id is not None:
                await push_relay.forget(relay_server_id)
            return (False, False)
        elif response.status_code == 403 and relay_server_id is not None:
            logger.error(
                "Push relay refused this server (status 403, %s byte answer)",
                len(response.content),
            )
            return (False, False)
        else:
            # Other error - don't delete token (might be temporary)
            logger.error(
                "%s request failed (status %s, %s byte answer)",
                service,
                response.status_code,
                len(response.content),
            )
            return (False, False)

    except httpx.TimeoutException:
        logger.warning("%s request timed out", service)
        return (False, False)
    except Exception:
        logger.exception("Failed to send push notification through %s", service)
        return (False, False)


@dataclass
class _Outcome:
    """What sending one push to one person's devices came to."""

    delivered_ids: list[int]
    dead_tokens: list[str]
    #: No device took it, and at least one send failed short of an answer —
    #: a timeout or a server error — so trying again later could still land.
    retry: bool


async def _send_to_devices(
    client: httpx.AsyncClient,
    tokens: Sequence[PushToken],
    *,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]],
    channel_id: str,
    badge: Optional[int] = None,
    gate: AsyncContextManager[Any] | None = None,
) -> _Outcome:
    """Send one push to each of these devices. ``gate`` bounds how many sends
    are in flight across a batch."""

    async def one(token: PushToken) -> tuple[bool, bool]:
        async with gate or nullcontext():
            return await send_push_notification(
                client,
                push_token=token.push_token,
                title=title,
                body=body,
                data=data,
                channel_id=channel_id,
                platform=token.platform,
                badge=badge,
            )

    results = await asyncio.gather(*(one(token) for token in tokens))
    outcome = _Outcome(delivered_ids=[], dead_tokens=[], retry=False)
    for token, (success, should_delete) in zip(tokens, results):
        if success:
            if token.id is not None:
                outcome.delivered_ids.append(token.id)
        elif should_delete:
            # Token is invalid (404/410 from FCM), mark for deletion
            logger.info("Deleting the invalid push token of device %s", token.id)
            outcome.dead_tokens.append(token.push_token)
        else:
            outcome.retry = True
    outcome.retry = outcome.retry and not outcome.delivered_ids
    return outcome


@dataclass(frozen=True)
class Push:
    """One push for one person, already worded and already allowed."""

    user_id: int
    notification_type: NotificationType
    title: str
    body: str
    data: Dict[str, Any]
    #: Only the devices these sign-ins registered; ``None`` for every device.
    session_ids: frozenset[uuid.UUID] | None = None


#: How many FCM calls one batch keeps in flight at once.
CONCURRENT_SENDS = 16


async def send_pushes(session: AsyncSession, pushes: Sequence[Push]) -> list[bool]:
    """Send a batch of pushes at once, on the system engine's ``session``.

    The one way a push leaves the app. Its caller has already applied the
    deployment's and the community's switches and each recipient's settings:
    this only finds each person's devices, keeps those a push names, sends,
    and records what FCM said. Each push carries its recipient's unread count
    for the app icon, read after the lines it announces were written. One HTTP
    client serves the batch and :data:`CONCURRENT_SENDS` calls are in flight at
    a time.

    Returns, for each push in order, whether it should be tried again: no device
    took it, and a send failed short of an answer. Does not commit.
    """
    if not pushes or not (await push_config.ensure_push_config_fresh()).enabled:
        return [False] * len(pushes)
    # One session, so the reads go one after another; the sends do not. Each
    # recipient's read and write is a savepoint of its own, so one that fails
    # costs that recipient's pushes alone.
    devices: dict[int, list[PushToken] | None] = {}
    for user_id in dict.fromkeys(push.user_id for push in pushes):
        try:
            async with session.begin_nested():
                devices[user_id] = await push_tokens.live_for_user(
                    session, user_id=user_id
                )
        except Exception:
            logger.exception("Could not read the devices of user %s", user_id)
            devices[user_id] = None
    # Without the count a push still goes, and leaves the badge as it was.
    unread: dict[int, int] | None
    try:
        async with session.begin_nested():
            unread = await user_notifications.unread_counts(session, list(devices))
    except Exception:
        logger.exception("Could not read the unread counts for a batch of pushes")
        unread = None
    gate = asyncio.Semaphore(CONCURRENT_SENDS)
    async with httpx.AsyncClient(timeout=10.0) as client:
        outcomes = await asyncio.gather(
            *(
                _send_to_devices(
                    client,
                    [
                        token
                        for token in devices[push.user_id] or []
                        if push.session_ids is None
                        or token.session_id in push.session_ids
                    ],
                    title=push.title,
                    body=push.body,
                    data=push.data,
                    channel_id=channel_for(push.notification_type),
                    badge=None if unread is None else unread.get(push.user_id, 0),
                    gate=gate,
                )
                for push in pushes
            )
        )
    for push, outcome in zip(pushes, outcomes):
        try:
            async with session.begin_nested():
                await push_tokens.record_delivery(
                    session,
                    user_id=push.user_id,
                    delivered_ids=outcome.delivered_ids,
                    dead_tokens=outcome.dead_tokens,
                )
        except Exception:
            # What was sent stays sent; only the bookkeeping is lost.
            logger.exception("Could not record a push for user %s", push.user_id)
    # A recipient whose devices could not be read was sent nothing.
    return [
        outcome.retry or devices[push.user_id] is None
        for push, outcome in zip(pushes, outcomes)
    ]
