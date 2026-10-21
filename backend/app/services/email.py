from __future__ import annotations

import asyncio
import logging
import html as _html
import re
import smtplib
import ssl
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from functools import lru_cache
from pathlib import Path
from typing import Literal, Mapping, Sequence

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.core.email_i18n import email_t
from app.core.notification_categories import CATEGORY_SPECS, NotificationCategory
from app.core.encryption import decrypt_field, SALT_SMTP_PASSWORD
from app.models.platform.access_grant import LEVEL_LABEL_KEYS
from app.models.platform.app_setting import AppSetting
from app.models.platform.user import User
from app.services.platform import app_settings as app_settings_service
from app.core.user_display import handle_of

try:  # premailer inlines our <style> rules so they survive Gmail/Outlook stripping <style>
    from premailer import transform as _premailer_transform
except Exception:  # pragma: no cover - optional dependency guard
    _premailer_transform = None  # ty: ignore[invalid-assignment]

logger = logging.getLogger(__name__)


class EmailNotConfiguredError(RuntimeError):
    pass


@dataclass
class SMTPConfig:
    host: str
    port: int
    secure: bool
    reject_unauthorized: bool
    username: str | None
    password: str | None
    from_address: str


def _accent_color(settings_obj: AppSetting | None) -> str:
    value = ""
    if settings_obj and settings_obj.light_accent_color:
        value = settings_obj.light_accent_color.strip()
    if not value or not re.match(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", value):
        return "#2563eb"
    return value


async def _email_context(session: AsyncSession) -> tuple[AppSetting, str]:
    settings_obj = await app_settings_service.get_app_settings(session)
    return settings_obj, _accent_color(settings_obj)


# Email clients (Gmail, Outlook, Yahoo) strip inline <svg>, so the brand mark is
# shipped as a raster PNG and embedded inline via a Content-ID reference. This
# displays without an external fetch — no "show images" prompt, no broken icon.
_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "email-logo.png"
LOGO_CID = "initiative-logo"


@lru_cache(maxsize=1)
def _logo_bytes() -> bytes | None:
    try:
        return _LOGO_PATH.read_bytes()
    except (
        OSError
    ):  # pragma: no cover - asset is committed; guard against odd packaging
        logger.warning("Email logo asset missing at %s", _LOGO_PATH)
        return None


def _build_html_layout(
    title: str, body: str, accent_color: str, locale: str = "en"
) -> str:
    footer_disclaimer = email_t("layout.footerDisclaimer", locale=locale)
    update_link_text = email_t("layout.updateNotifications", locale=locale)
    return f"""\
<html>
  <body style="font-family:'Outfit','Inter','Segoe UI',Arial,sans-serif;color:#0f172a;background-color:#f3f4f6;padding:24px;">
    <div style="max-width:520px;margin:0 auto;background-color:#ffffff;padding:28px;border-radius:16px;border:1px solid #e2e8f0;box-shadow:0 10px 40px rgba(15,23,42,0.08);">
      <style>
        a {{
          color: {accent_color};
          text-decoration: none;
          font-weight: 600;
        }}
      </style>
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:24px;">
        <a href="{app_config.APP_URL}" style="display:inline-block;">
          <img src="cid:{LOGO_CID}" width="44" height="44" alt="Initiative" style="display:block;width:44px;height:44px;border:0;border-radius:12px;" />
        </a>
        <div>
          <p style="margin:0;font-size:18px;font-weight:700;color:{accent_color};"><a href="{app_config.APP_URL}">initiative</a></p>
        </div>
      </div>
      <h2 style="margin-top:0;font-size:22px;color:#0f172a;">{title}</h2>
      <div style="font-size:15px;line-height:1.5;color:#334155;">{body}</div>
      <p style="font-size:12px;color:#94a3b8;margin-top:32px;">
        {footer_disclaimer}
      </p>
      <p>
        <a href="{app_config.APP_URL}/profile/notifications">{update_link_text}</a>
      </p>
    </div>
  </body>
</html>
"""


def _strip_html(html: str) -> str:
    """Reduce an HTML email fragment to its plain-text alternative.

    Strips trusted template tags, then unescapes entities so values that were
    HTML-escaped for the HTML part (see ``email_i18n``) read as the user's
    literal text in the text/plain part.

    Deliberate consequence: a user-supplied value that itself looks like markup
    (e.g. a display name of ``<a href="https://x">…</a>``) appears verbatim in
    the text part — including any URL, which a client's auto-linkification may
    make clickable. That is acceptable for text/plain (no styling or trust
    cues, unlike the brand-styled HTML part), and the alternative — leaving
    entities encoded — would corrupt legitimate names like ``Tom & Jerry``.
    """
    return _html.unescape(re.sub(r"<[^>]+>", "", html))


def _build_smtp_config(settings_obj: AppSetting) -> SMTPConfig:
    """The connection settings, without the password (see ``_smtp_password``)."""
    host = settings_obj.smtp_host
    from_address = settings_obj.smtp_from_address
    if not host or not from_address:
        raise EmailNotConfiguredError("SMTP host or from address missing")
    port = settings_obj.smtp_port or (465 if settings_obj.smtp_secure else 587)
    return SMTPConfig(
        host=host,
        port=port,
        secure=bool(settings_obj.smtp_secure),
        reject_unauthorized=bool(settings_obj.smtp_reject_unauthorized),
        username=settings_obj.smtp_username,
        password=None,
        from_address=from_address,
    )


async def _smtp_password() -> str | None:
    """The stored SMTP password, decrypted, or ``None`` when none is stored.

    Read on a system-engine session of its own: ``app_setting_secrets`` is
    granted to no request-path role, and a message goes out from whichever
    session its caller holds.
    """
    secrets_row = await app_settings_service.load_app_setting_secrets()
    if not secrets_row.smtp_password_encrypted:
        return None
    return decrypt_field(secrets_row.smtp_password_encrypted, SALT_SMTP_PASSWORD)


def _smtp_context(reject_unauthorized: bool) -> ssl.SSLContext:
    if reject_unauthorized:
        return ssl.create_default_context()
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _deliver(config: SMTPConfig, message: EmailMessage) -> None:
    context = _smtp_context(config.reject_unauthorized)
    if config.secure:
        with smtplib.SMTP_SSL(config.host, config.port, context=context) as client:
            _send_via_client(client, config, message)
    else:
        with smtplib.SMTP(config.host, config.port) as client:
            client.ehlo()
            try:
                client.starttls(context=context)
                client.ehlo()
            except smtplib.SMTPException:
                logger.debug(
                    "STARTTLS not available for SMTP host %s:%s",
                    config.host,
                    config.port,
                )
            _send_via_client(client, config, message)


def _send_via_client(
    client: smtplib.SMTP, config: SMTPConfig, message: EmailMessage
) -> None:
    if config.username and config.password:
        client.login(config.username, config.password)
    client.send_message(message)


def _user_locale(user: User) -> str:
    return getattr(user, "locale", None) or "en"


def _inline_css(html: str) -> str:
    """Inline <style> rules into element style attributes via premailer.

    Gmail's mobile app and several clients strip <style> blocks, which would
    drop our link colours/weights. Inlining makes them survive. Failures here
    must never block an email, so we fall back to the original HTML.
    """
    if _premailer_transform is None:
        return html
    try:
        return _premailer_transform(
            html,
            keep_style_tags=False,
            remove_classes=True,
            disable_validation=True,
            cssutils_logging_level=logging.CRITICAL,
        )
    except Exception:  # pragma: no cover - defensive: never fail send over styling
        logger.warning(
            "premailer CSS inlining failed; sending un-inlined HTML", exc_info=True
        )
        return html


def _cta_button(label: str, link: str, accent: str) -> str:
    return (
        f'<a href="{link}" style="background-color:{accent};color:#ffffff;'
        f"padding:12px 18px;border-radius:8px;text-decoration:none;"
        f'font-weight:600;display:inline-block;">{label}</a>'
    )


def _embed_logo(message: EmailMessage) -> None:
    """Attach the brand logo as an inline image referenced by ``cid:LOGO_CID``.

    The HTML alternative is wrapped in a multipart/related part holding the PNG,
    so the logo renders inline without an external fetch. No-op when the asset
    is missing (the <img> alt text shows instead).
    """
    logo = _logo_bytes()
    if not logo:
        return
    payload = message.get_payload()
    if not isinstance(payload, list):
        return
    # Locate the text/html alternative explicitly rather than assuming a
    # position, so this stays correct regardless of how the message was built.
    html_part = next(
        (part for part in payload if part.get_content_type() == "text/html"), None
    )
    if html_part is None:
        return
    html_part.add_related(logo, "image", "png", cid=f"<{LOGO_CID}>")


async def send_email(
    session: AsyncSession,
    *,
    recipients: Sequence[str],
    subject: str,
    html_body: str,
    text_body: str | None = None,
    settings_obj: AppSetting | None = None,
) -> None:
    if not recipients:
        raise ValueError("At least one recipient email is required")
    from app.demo import samples as demo_samples

    # The demo's sample accounts sign in with addresses nobody reads.
    shared = await demo_samples.addresses_of(recipients)
    if shared:
        recipients = [address for address in recipients if address not in shared]
        if not recipients:
            return
    if settings_obj is None:
        settings_obj = await app_settings_service.get_app_settings(session)
    # Built before the password is read: an install with no mail server raises
    # here without opening a system-engine session.
    config = _build_smtp_config(settings_obj)
    config.password = await _smtp_password()
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.from_address
    message["To"] = ", ".join(recipients)
    plain = text_body or _strip_html(html_body)
    message.set_content(plain)
    message.add_alternative(_inline_css(html_body), subtype="html")
    _embed_logo(message)
    try:
        await asyncio.to_thread(_deliver, config, message)
    except EmailNotConfiguredError:
        raise
    except Exception as exc:
        # Records the failure's type and SMTP reply code; the error raised to
        # callers carries no chained cause.
        if isinstance(exc, smtplib.SMTPResponseException):
            logger.error(
                "Failed to send email (%s, code %s)", type(exc).__name__, exc.smtp_code
            )
        else:
            logger.error("Failed to send email (%s)", type(exc).__name__)
        raise RuntimeError("Failed to send email") from None


async def send_test_email(session: AsyncSession, recipient: str) -> None:
    settings_obj, accent = await _email_context(session)
    locale = "en"
    html_body = _build_html_layout(
        email_t("test.title", locale=locale),
        f"<p>{email_t('test.body', locale=locale)}</p>",
        accent,
        locale=locale,
    )
    await send_email(
        session,
        recipients=[recipient],
        subject=email_t("test.subject", locale=locale, escape=False),
        html_body=html_body,
        text_body=email_t("test.body", locale=locale, escape=False),
        settings_obj=settings_obj,
    )


def _frontend_url(path: str) -> str:
    base = app_config.APP_URL.rstrip("/")
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


def account_change_link(token: str) -> str:
    """The page a "This wasn't me" button in an account letter opens."""
    return _frontend_url(f"/account/not-me?token={token}")


async def send_verification_email(
    session: AsyncSession, user: User, token: str
) -> None:
    settings_obj, accent = await _email_context(session)
    locale = _user_locale(user)
    name = handle_of(user)
    link = _frontend_url(f"/verify-email?token={token}")
    button = _cta_button(
        email_t("verification.buttonLabel", locale=locale), link, accent
    )
    body = f"""
    <p>{email_t("verification.greeting", locale=locale, name=name)}</p>
    <p>{email_t("verification.body", locale=locale)}</p>
    <p style="margin:24px 0;">{button}</p>
    <p>{email_t("verification.fallbackText", locale=locale)}<br/><code>{link}</code></p>
    """
    html_body = _build_html_layout(
        email_t("verification.title", locale=locale), body, accent, locale=locale
    )
    text_body = email_t("verification.textBody", locale=locale, link=link, escape=False)
    await _send_to_primary(
        session,
        user,
        subject=email_t("verification.subject", locale=locale, escape=False),
        html_body=html_body,
        text_body=text_body,
        settings_obj=settings_obj,
    )


async def _account_recipients(user: User) -> list[str]:
    """Where a letter about the account itself goes: every address its holder
    has proved (§6.2 rule 4), so a change nobody made is still seen by somebody
    who no longer reads one of them.

    On its own system-engine session rather than the caller's. Which addresses
    an account holds is reached there and nowhere else, and the callers here
    arrive with whichever session their endpoint runs on — a password reset
    with the request-path one, an operator's reset with the system one.
    """
    from app.db.session import SystemSessionLocal
    from app.services.auth import addresses

    async with SystemSessionLocal() as system_session:
        return await addresses.proven_addresses(system_session, user_id=user.id)


async def _send_to_primary(
    session: AsyncSession,
    user: User,
    *,
    subject: str,
    html_body: str,
    text_body: str | None = None,
    settings_obj: AppSetting | None = None,
) -> None:
    """Send one letter to the address this account nominated.

    Everything that is not about the account itself comes through here: a
    mention, a digest, an invitation. Account mail fans out over every proven
    address instead (``_account_recipients``, §6.2 rule 4).

    On its own system-engine session, for the reason ``_account_recipients``
    gives. An account with no primary address is not written to.
    """
    from app.db.session import SystemSessionLocal
    from app.services.auth import addresses

    async with SystemSessionLocal() as system_session:
        address = await addresses.primary_address(system_session, user_id=user.id)
    if address is None:
        logger.warning("no primary address for account %s; not sending", user.id)
        return
    await send_email(
        session,
        recipients=[address],
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        settings_obj=settings_obj,
    )


# ---------------------------------------------------------------------------
# Pieces
#
# A notification email is written down before it is sent (see
# ``app.services.platform.email_outbox``), so what a notifier produces is not a
# finished message but the parts of one: what it is about, what it says, and
# where it goes. On its own that renders exactly the email that used to be sent
# inline. Alongside others it becomes one line of a digest, without being
# re-rendered — which is what makes a line in a digest read the way its own
# email would have.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EmailPieces:
    """One notification's worth of email, before it is a message."""

    #: The subject, if this goes out on its own. A digest writes its own.
    subject: str
    #: The heading, if this goes out on its own.
    headline: str
    #: What happened, as an HTML fragment. No greeting and no button: those
    #: belong to the message, and a digest carries many of these.
    body: str
    link: str | None = None
    #: What the button says when this goes out on its own.
    link_label: str | None = None


@dataclass(frozen=True)
class DigestLine:
    """One row of a digest, as the composer needs it."""

    category: str
    guild_id: int | None
    body: str
    link: str | None


def _greeting(locale: str, name: str) -> str:
    return email_t("mention.greeting", locale=locale, name=name)


def render_single(
    pieces: EmailPieces, *, user: User, accent: str, locale: str
) -> tuple[str, str]:
    """One notification as its own message — the shape this app has always
    sent. Returns ``(html, text)``."""
    name = handle_of(user)
    button = ""
    if pieces.link:
        label = pieces.link_label or email_t("mention.buttonLabel", locale=locale)
        button = (
            f'<p style="margin:24px 0;">{_cta_button(label, pieces.link, accent)}</p>'
        )
    body = f"""
    <p>{_greeting(locale, name)}</p>
    <p>{pieces.body}</p>
    {button}
    """
    html_body = _build_html_layout(pieces.headline, body, accent, locale=locale)
    # The body is an HTML fragment (locale strings bold their values via
    # <strong>), so the plain-text alternative is it with the tags taken out.
    plain = _strip_html(pieces.body)
    if pieces.link:
        plain += f"\n\nView: {pieces.link}"
    return html_body, plain


def render_digest(
    lines: Sequence[DigestLine],
    *,
    user: User,
    accent: str,
    locale: str,
    reason: str,
    guild_names: Mapping[int, str],
) -> tuple[str, str, str]:
    """Several notifications as one message. Returns ``(subject, html, text)``.

    Grouped by community and then by category, because that is how somebody
    reads it: which of my communities wants me, and what for. Rows arrive in
    the order they were written, which inside a category is the order the
    things happened.

    ``reason`` is why this batch is going out now — a cadence
    (``hourly``/``daily``/``weekly``) or ``away``, for a batch a hold released.
    """
    name = handle_of(user)
    total = len(lines)
    title = email_t(f"digest.{reason}.title", locale=locale)
    subject = email_t(
        f"digest.{reason}.subject", locale=locale, count=total, escape=False
    )

    grouped: dict[int | None, dict[str, list[DigestLine]]] = {}
    for line in lines:
        grouped.setdefault(line.guild_id, {}).setdefault(line.category, []).append(line)

    def _place(guild_id: int | None, category: str) -> str:
        if guild_id is not None:
            return guild_names.get(guild_id) or email_t(
                "digest.noCommunity.other", locale=locale
            )
        # Rows with no community are usually the things that belong to none —
        # direct messages, connections, account notices — and those are named
        # by what they are. A category that *does* belong to a community and
        # arrived without one is a digest spanning several, so it is named as
        # that rather than as something it is not.
        try:
            spec = CATEGORY_SPECS[NotificationCategory(category)]
        except (KeyError, ValueError):
            return email_t("digest.noCommunity.other", locale=locale)
        if spec.guild_scoped:
            return email_t("digest.noCommunity.other", locale=locale)
        return email_t(f"digest.noCommunity.{category}", locale=locale)

    html_parts: list[str] = [f"<p>{_greeting(locale, name)}</p>"]
    text_parts: list[str] = [
        email_t(f"digest.{reason}.title", locale=locale, escape=False),
        "",
    ]
    for guild_id, by_category in grouped.items():
        heading = _place(guild_id, next(iter(by_category)))
        html_parts.append(
            f'<h3 style="margin:24px 0 4px;font-size:16px;">{_html.escape(heading)}</h3>'
        )
        text_parts.append(heading)
        for category, rows in by_category.items():
            label = email_t(f"digest.category.{category}", locale=locale)
            html_parts.append(
                f'<p style="margin:12px 0 2px;font-weight:600;color:#64748b;'
                f'font-size:13px;">{label}</p><ul style="margin:0;">'
            )
            text_parts.append(f"  {_strip_html(label)}")
            for row in rows:
                inner = f'<a href="{row.link}">{row.body}</a>' if row.link else row.body
                html_parts.append(f"<li>{inner}</li>")
                line_text = f"    - {_strip_html(row.body)}"
                if row.link:
                    line_text += f" -> {row.link}"
                text_parts.append(line_text)
            html_parts.append("</ul>")

    html_body = _build_html_layout(title, "".join(html_parts), accent, locale=locale)
    return subject, html_body, "\n".join(text_parts)


async def deliver(
    session: AsyncSession,
    user: User,
    *,
    subject: str,
    html_body: str,
    text_body: str,
    every_address: bool = False,
    recipient: str | None = None,
) -> None:
    """Put a composed message on the wire, to the address this account
    nominated — or to the one ``recipient`` a letter names, or, for a letter
    about the account itself written before letters named one, to every
    address it has proved. The one exit from the outbox."""
    settings_obj = await app_settings_service.get_app_settings(session)
    if recipient is not None:
        await send_email(
            session,
            recipients=[recipient],
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            settings_obj=settings_obj,
        )
        return
    if every_address:
        await send_email(
            session,
            recipients=await _account_recipients(user),
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            settings_obj=settings_obj,
        )
        return
    await _send_to_primary(
        session,
        user,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        settings_obj=settings_obj,
    )


async def email_configured(session: AsyncSession) -> bool:
    """Whether this deployment can send mail at all.

    Asked before writing a row rather than after: an install with no mail
    server should not accumulate a queue nothing will ever drain.
    """
    settings_obj = await app_settings_service.get_app_settings(session)
    try:
        _build_smtp_config(settings_obj)
    except EmailNotConfiguredError:
        return False
    return True


async def email_context(session: AsyncSession) -> tuple[AppSetting, str]:
    """The deployment's mail settings and accent, for a composer."""
    return await _email_context(session)


async def send_address_verification_email(
    session: AsyncSession, user: User, *, address: str, token: str
) -> None:
    """Prove one address, by writing to that address.

    The same letter as the account-level verification, addressed to the one
    being added rather than to the account's own — it is the only thing an
    unverified address ever receives.
    """
    settings_obj, accent = await _email_context(session)
    locale = _user_locale(user)
    name = handle_of(user)
    link = _frontend_url(f"/verify-email?token={token}")
    button = _cta_button(
        email_t("verification.buttonLabel", locale=locale), link, accent
    )
    body = f"""
    <p>{email_t("verification.greeting", locale=locale, name=name)}</p>
    <p>{email_t("verification.body", locale=locale)}</p>
    <p style="margin:24px 0;">{button}</p>
    <p>{email_t("verification.fallbackText", locale=locale)}<br/><code>{link}</code></p>
    """
    html_body = _build_html_layout(
        email_t("verification.title", locale=locale), body, accent, locale=locale
    )
    text_body = email_t("verification.textBody", locale=locale, link=link, escape=False)
    await send_email(
        session,
        recipients=[address],
        subject=email_t("verification.subject", locale=locale, escape=False),
        html_body=html_body,
        text_body=text_body,
        settings_obj=settings_obj,
    )


async def send_password_reset_email(
    session: AsyncSession, user: User, token: str
) -> None:
    settings_obj, accent = await _email_context(session)
    locale = _user_locale(user)
    name = handle_of(user)
    link = _frontend_url(f"/reset-password?token={token}")
    button = _cta_button(
        email_t("passwordReset.buttonLabel", locale=locale), link, accent
    )
    body = f"""
    <p>{email_t("passwordReset.greeting", locale=locale, name=name)}</p>
    <p>{email_t("passwordReset.body", locale=locale)}</p>
    <p style="margin:24px 0;">{button}</p>
    <p>{email_t("passwordReset.fallbackText", locale=locale)}</p>
    """
    html_body = _build_html_layout(
        email_t("passwordReset.title", locale=locale), body, accent, locale=locale
    )
    text_body = email_t(
        "passwordReset.textBody", locale=locale, link=link, escape=False
    )
    await send_email(
        session,
        recipients=await _account_recipients(user),
        subject=email_t("passwordReset.subject", locale=locale, escape=False),
        html_body=html_body,
        text_body=text_body,
        settings_obj=settings_obj,
    )


async def send_sign_in_code_email(
    session: AsyncSession, user: User, *, email: str, code: str, minutes: int
) -> None:
    """Send a one-time sign-in code to the address it was asked about.

    To that one address, not to every address the account has proved: the code
    answers a question somebody asked about a particular mailbox, and the
    account's other addresses did not ask.

    No link and no button. The code is typed back into the page that asked for
    it, which is the whole shape of this way in.
    """
    settings_obj, accent = await _email_context(session)
    locale = _user_locale(user)
    name = handle_of(user)
    shown = (
        f'<p style="margin:24px 0;font-size:32px;font-weight:700;'
        f'letter-spacing:0.25em;color:{accent};">{code}</p>'
    )
    body = f"""
    <p>{email_t("signInCode.greeting", locale=locale, name=name)}</p>
    <p>{email_t("signInCode.body", locale=locale)}</p>
    {shown}
    <p>{email_t("signInCode.expiry", locale=locale, minutes=minutes)}</p>
    <p>{email_t("signInCode.fallbackText", locale=locale)}</p>
    """
    html_body = _build_html_layout(
        email_t("signInCode.title", locale=locale), body, accent, locale=locale
    )
    await send_email(
        session,
        recipients=[email],
        subject=email_t("signInCode.subject", locale=locale, escape=False),
        html_body=html_body,
        text_body=email_t(
            "signInCode.textBody",
            locale=locale,
            code=code,
            minutes=minutes,
            escape=False,
        ),
        settings_obj=settings_obj,
    )


async def send_sign_up_code_email(
    session: AsyncSession, *, email: str, code: str, minutes: int, locale: str
) -> None:
    """Send a one-time code to an address no account holds yet.

    There is no account, so there is no name to greet and no stored language
    to write in: the locale is the one the browser asked in.
    """
    settings_obj, accent = await _email_context(session)
    shown = (
        f'<p style="margin:24px 0;font-size:32px;font-weight:700;'
        f'letter-spacing:0.25em;color:{accent};">{code}</p>'
    )
    body = f"""
    <p>{email_t("signUpCode.greeting", locale=locale)}</p>
    <p>{email_t("signUpCode.body", locale=locale)}</p>
    {shown}
    <p>{email_t("signUpCode.expiry", locale=locale, minutes=minutes)}</p>
    <p>{email_t("signUpCode.fallbackText", locale=locale)}</p>
    """
    html_body = _build_html_layout(
        email_t("signUpCode.title", locale=locale), body, accent, locale=locale
    )
    await send_email(
        session,
        recipients=[email],
        subject=email_t("signUpCode.subject", locale=locale, escape=False),
        html_body=html_body,
        text_body=email_t(
            "signUpCode.textBody",
            locale=locale,
            code=code,
            minutes=minutes,
            escape=False,
        ),
        settings_obj=settings_obj,
    )


async def send_account_erased_email(
    session: AsyncSession, *, recipients: list[str], locale: str = "en"
) -> None:
    """Tell an account that it is gone, at the addresses it proved.

    The recipients are passed in rather than read from the account, because by
    the time this is worth sending there is no account to read them from —
    the caller captures them before the erasure and hands them over after it
    commits.

    No name and no link: the person it names has been unnamed, and there is
    nowhere left for them to go.
    """
    settings_obj, accent = await _email_context(session)
    body = f"""
    <p>{email_t("accountErased.greeting", locale=locale)}</p>
    <p>{email_t("accountErased.body", locale=locale)}</p>
    <p>{email_t("accountErased.kept", locale=locale)}</p>
    <p>{email_t("accountErased.unexpected", locale=locale)}</p>
    """
    html_body = _build_html_layout(
        email_t("accountErased.title", locale=locale), body, accent, locale=locale
    )
    await send_email(
        session,
        recipients=recipients,
        subject=email_t("accountErased.subject", locale=locale, escape=False),
        html_body=html_body,
        text_body=email_t("accountErased.textBody", locale=locale, escape=False),
        settings_obj=settings_obj,
    )


async def announce_account_erased(
    session: AsyncSession, *, recipients: list[str], locale: str = "en"
) -> None:
    """Send the receipt, and never fail the erasure because it could not go.

    By the time this runs the account is gone and committed. A deployment with
    no mail configured still erased it, and answering the request with a
    failure would say otherwise.
    """
    if not recipients:
        return
    try:
        await send_account_erased_email(session, recipients=recipients, locale=locale)
    except EmailNotConfiguredError:
        logger.info("no mail configured; erasure not acknowledged by letter")
    except Exception:  # pragma: no cover - delivery is best-effort here
        logger.exception("could not send the erasure receipt")


async def send_community_deleted_email(
    session: AsyncSession,
    *,
    recipients: list[str],
    community: str,
    purge_at: datetime | None,
    locale: str = "en",
) -> None:
    """Tell the people who ran a community that it is gone.

    Its members learn from it leaving their lists, which is the thing they can
    act on. The people who ran it get this, because the one action left —
    asking an operator to put it back — is theirs, and it has a deadline.
    """
    settings_obj, accent = await _email_context(session)
    recoverable = (
        email_t(
            "communityDeleted.recoverable",
            locale=locale,
            date=purge_at.strftime("%-d %B %Y"),
        )
        if purge_at is not None
        else email_t("communityDeleted.recoverableNoDate", locale=locale)
    )
    body = f"""
    <p>{email_t("communityDeleted.greeting", locale=locale)}</p>
    <p>{email_t("communityDeleted.body", locale=locale, community=community)}</p>
    <p>{recoverable}</p>
    """
    html_body = _build_html_layout(
        email_t("communityDeleted.title", locale=locale, community=community),
        body,
        accent,
        locale=locale,
    )
    await send_email(
        session,
        recipients=recipients,
        subject=email_t(
            "communityDeleted.subject", locale=locale, community=community, escape=False
        ),
        html_body=html_body,
        text_body=email_t(
            "communityDeleted.textBody",
            locale=locale,
            community=community,
            escape=False,
        ),
        settings_obj=settings_obj,
    )


async def announce_community_deleted(
    session: AsyncSession, notice, *, locale: str = "en"
) -> None:
    """Send the receipt, and never fail the deletion because it could not go.

    By the time this runs the community is deleted and committed. A deployment
    with no mail configured still deleted it.
    """
    if not notice.recipients:
        return
    try:
        await send_community_deleted_email(
            session,
            recipients=notice.recipients,
            community=notice.community_name,
            purge_at=notice.purge_at,
            locale=locale,
        )
    except EmailNotConfiguredError:
        logger.info("no mail configured; community deletion not acknowledged")
    except Exception:  # pragma: no cover - delivery is best-effort here
        logger.exception("could not send the community deletion receipt")


def email_date(value: date | datetime, locale: str = "en") -> str:
    """A calendar day as a letter in ``locale`` writes one ("24 October 2026",
    "24. Oktober 2026"). Month names come from the locale files, so a
    language without them falls back to English like every other string."""
    month = email_t(f"dates.months.m{value.month}", locale=locale, escape=False)
    return email_t(
        "dates.long",
        locale=locale,
        day=value.day,
        month=month,
        year=value.year,
        escape=False,
    )


def community_on_hold_pieces(
    *,
    community: str,
    contact: str | None,
    guild_id: int,
    delete_at: datetime | None,
    plan_managed: bool,
    locale: str,
) -> EmailPieces:
    """A community's hold as a letter, in ``locale``: that it is on hold, whom
    to contact about it, and, where the hold runs out, when it is deleted.

    ``delete_at`` is None where this deployment never deletes a held community.
    ``plan_managed`` says what lifts the hold: on a deployment whose plans the
    billing service sets, restoring the plan, which the letter's button leads
    to; elsewhere, whoever put it there, and the letter has no button. Queued
    as account mail, to every address each seat holder has proved.
    """
    next_step = (
        email_t("communityOnHold.contact", locale=locale, contact=contact)
        if contact
        else email_t("communityOnHold.contactNobody", locale=locale)
    )
    day = email_date(delete_at, locale) if delete_at is not None else None
    if day is None:
        body_key = "body"
    elif plan_managed:
        body_key = "bodyDeleting"
    else:
        body_key = "bodyDeletingUnlessLifted"
    body = email_t(
        f"communityOnHold.{body_key}",
        locale=locale,
        community=community,
        date=day or "",
    )
    return EmailPieces(
        subject=email_t(
            "communityOnHold.subject", locale=locale, community=community, escape=False
        ),
        headline=email_t("communityOnHold.title", locale=locale, community=community),
        body=f"{body} {next_step}",
        # Where billing sets plans, restoring the plan lifts the hold, so the
        # letter leads there.
        link=community_billing_link(guild_id, "manage") if plan_managed else None,
        link_label=(
            email_t("communityOnHold.buttonLabel", locale=locale)
            if plan_managed
            else None
        ),
    )


#: The section of ``email.json`` each billing notice is written from, and the
#: billing portal page its button leads to.
_BILLING_NOTICE_SECTIONS: dict[str, tuple[str, Literal["upgrade", "manage"]]] = {
    "trial_ending": ("communityTrialEnding", "manage"),
    "trial_ended": ("communityTrialEnded", "upgrade"),
    "pause_reminder": ("communityPauseReminder", "manage"),
}


def community_billing_notice_pieces(
    *, kind: str, community: str, day: date, guild_id: int, locale: str
) -> EmailPieces:
    """A billing notice as notification mail, in ``locale``.

    ``kind`` is one of the billing notice kinds; the words are this
    deployment's. A trial is Paddle's: a community in one is already
    subscribed, and its plan is billed when the trial ends unless it is
    cancelled first. A pause is its admin's: the community is read-only and
    unbilled until they resume it, and goes on hold on ``day`` if they do not.
    Written into the notice outbox beside the bell line, so the outbox worker
    sends it and retries it; the button leads to the community's billing page,
    which signs the reader in and forwards them to the billing portal — to the
    plan they have, where a pause is resumed, or to choosing one once a trial
    has ended without a payment.
    """
    section, page = _BILLING_NOTICE_SECTIONS[kind]
    shown = email_date(day, locale)
    return EmailPieces(
        subject=email_t(
            f"{section}.subject",
            locale=locale,
            community=community,
            date=shown,
            escape=False,
        ),
        headline=email_t(
            f"{section}.title", locale=locale, community=community, date=shown
        ),
        body=email_t(f"{section}.body", locale=locale, community=community, date=shown),
        link=community_billing_link(guild_id, page),
        link_label=email_t(f"{section}.buttonLabel", locale=locale),
    )


def community_welcome_pieces(
    *, community: str, guild_id: int, locale: str
) -> EmailPieces:
    """A newly made community's welcome as notification mail, in ``locale``.

    Written into the notice outbox beside the bell line, like a trial notice;
    the button leads to the community's billing page, where its plan is set up.
    """
    return EmailPieces(
        subject=email_t(
            "communityWelcome.subject", locale=locale, community=community, escape=False
        ),
        headline=email_t("communityWelcome.title", locale=locale, community=community),
        body=email_t("communityWelcome.body", locale=locale, community=community),
        link=community_billing_link(guild_id, "upgrade"),
        link_label=email_t("communityWelcome.buttonLabel", locale=locale),
    )


def community_billing_link(guild_id: int, page: Literal["upgrade", "manage"]) -> str:
    """The community's billing page, for a letter's button. It signs the
    reader in and forwards them to the billing portal's ``page``: ``upgrade``
    to choose a plan, ``manage`` to look after the one it has."""
    return _frontend_url(f"/c/{guild_id}/billing?page={page}")


async def _queue_account_notice(
    user: User,
    *,
    section: str,
    key: str,
    answerable: bool = True,
    also_to: Sequence[str] = (),
    record: Mapping[str, object] | None = None,
    **values: str,
) -> None:
    """Queue one letter about a way into the account changing.

    Account mail: it goes out at once, on its own, to every address its holder
    has proved, whatever their notification settings — a change nobody made is
    still seen by somebody who no longer reads one of them — and to
    ``also_to`` beside them. ``section`` holds the greeting and the "if this
    wasn't you" line every letter of its kind shares; ``key`` holds what this
    one says. An ``answerable`` letter carries a "This wasn't me" link, and
    ``record`` says what that link may undo (``account_changes.change_record``).

    Called once the change is committed, and never allowed to fail it: the
    change was made whether or not the letter can go.
    """
    from app.services.platform import email_outbox

    pieces = _account_notice_pieces(user, section=section, key=key, **values)
    try:
        await email_outbox.enqueue_account_letter(
            user,
            pieces,
            change={"notice": key, **(record or {})} if answerable else None,
            also_to=also_to,
        )
    except Exception:  # pragma: no cover - the letter is best effort
        logger.exception("could not queue %s for account %s", key, user.id)


def _account_notice_pieces(
    user: User, *, section: str, key: str, **values: str
) -> EmailPieces:
    """One letter about a way into the account changing, in its holder's
    locale."""
    locale = _user_locale(user)
    return EmailPieces(
        subject=email_t(f"{key}.subject", locale=locale, escape=False),
        headline=email_t(f"{key}.title", locale=locale),
        body=(
            f"{email_t(f'{key}.body', locale=locale, **values)}</p>\n\n"
            f"<p>{email_t(f'{section}.fallbackText', locale=locale)}"
        ),
    )


async def announce_second_factor_change(
    session: AsyncSession, user: User, *, enabled: bool
) -> None:
    """Tell the account its second factor was turned on or off."""
    await _queue_account_notice(
        user,
        section="secondFactor",
        key="secondFactor.enabled" if enabled else "secondFactor.disabled",
    )


async def announce_recovery_codes_issued(session: AsyncSession, user: User) -> None:
    """Tell the account a new set of recovery codes was made, and the old
    ones stopped working."""
    await _queue_account_notice(
        user, section="secondFactor", key="secondFactor.recoveryRegenerated"
    )


async def announce_identity_linked(
    session: AsyncSession, user: User, *, provider: str
) -> None:
    """Tell the account it can now be signed in to through ``provider``."""
    await _queue_account_notice(
        user, section="identity", key="identity.linked", provider=provider
    )


async def announce_passkey_change(
    session: AsyncSession,
    user: User,
    *,
    added: bool,
    name: str,
    record: Mapping[str, object] | None = None,
) -> None:
    """Tell the account a passkey was added or removed."""
    await _queue_account_notice(
        user,
        section="passkey",
        key="passkey.added" if added else "passkey.removed",
        record=record,
        passkey=name,
    )


async def announce_address_change(
    session: AsyncSession,
    user: User,
    *,
    change: Literal["proved", "primary"],
    address: str,
    record: Mapping[str, object] | None = None,
) -> None:
    """Tell the account an address was proved on it, or made its primary."""
    await _queue_account_notice(
        user,
        section="address",
        key=f"address.{change}",
        record=record,
        address=address,
    )


async def announce_address_removed(
    session: AsyncSession,
    user: User,
    *,
    address: str,
    record: Mapping[str, object] | None = None,
) -> None:
    """Tell the account a proved address was removed, and tell that address.

    The account's own addresses no longer include it, so it is named as a
    recipient of its own.
    """
    await _queue_account_notice(
        user,
        section="address",
        key="address.removed",
        also_to=[address],
        record=record,
        address=address,
    )


#: The letter each held change sends, by kind, and what it names.
_HELD_NOTICES: dict[str, tuple[str, str]] = {
    "primary": ("address", "address.primaryHeld"),
    "remove_address": ("address", "address.removalHeld"),
    "second_factor_off": ("secondFactor", "secondFactor.disableHeld"),
    "last_passkey": ("passkey", "passkey.removalHeld"),
}


async def announce_held_change(
    user: User,
    *,
    kind: str,
    subject: str | None,
    applies_at: datetime,
    record: Mapping[str, object],
) -> None:
    """Tell the account a change to it waits until ``applies_at``. Its link
    cancels the change, where the copy may."""
    section, key = _HELD_NOTICES[kind]
    await _queue_account_notice(
        user,
        section=section,
        key=key,
        record=record,
        date=email_date(applies_at, _user_locale(user)),
        address=subject or "",
        passkey=subject or "",
    )


async def announce_sign_in_locked(
    session: AsyncSession, user: User, *, lock_for: timedelta
) -> None:
    """Tell the account its password and codes are turned off, and for how long."""
    minutes = int(lock_for.total_seconds()) // 60
    if minutes < 60:
        await _queue_account_notice(
            user,
            section="signInLocked",
            key="signInLocked.locked",
            answerable=False,
            minutes=str(minutes),
        )
    else:
        await _queue_account_notice(
            user,
            section="signInLocked",
            key="signInLocked.lockedHours",
            answerable=False,
            count=str(minutes // 60),
        )


async def announce_password_removed(session: AsyncSession, user: User) -> None:
    """Tell the account its password is gone and what signs it in now."""
    await _queue_account_notice(user, section="passwordRemoved", key="passwordRemoved")


async def announce_password_changed(session: AsyncSession, user: User) -> None:
    """Tell the account its password was changed."""
    await _queue_account_notice(user, section="passwordChanged", key="passwordChanged")


def initiative_added_pieces(user: User, initiative_name: str) -> EmailPieces:
    locale = _user_locale(user)
    link = _frontend_url("/initiatives")
    return EmailPieces(
        subject=email_t(
            "initiativeAdded.subject",
            locale=locale,
            initiativeName=initiative_name,
            escape=False,
        ),
        headline=email_t("initiativeAdded.title", locale=locale),
        body=email_t(
            "initiativeAdded.body", locale=locale, initiativeName=initiative_name
        ),
        link=link,
        link_label=email_t("initiativeAdded.buttonLabel", locale=locale),
    )


def project_added_pieces(
    user: User,
    *,
    initiative_name: str,
    project_name: str,
    project_id: int,
) -> EmailPieces:
    locale = _user_locale(user)
    return EmailPieces(
        subject=email_t(
            "projectAdded.subject",
            locale=locale,
            initiativeName=initiative_name,
            escape=False,
        ),
        headline=email_t("projectAdded.title", locale=locale),
        body=email_t(
            "projectAdded.body",
            locale=locale,
            projectName=project_name,
            initiativeName=initiative_name,
        ),
        link=_frontend_url(f"/projects/{project_id}"),
        link_label=email_t("projectAdded.buttonLabel", locale=locale),
    )


def access_grant_pieces(
    user: User,
    *,
    event: str,
    guild_name: str,
    levels: Sequence[str] | None = None,
    requester: str | None = None,
) -> EmailPieces:
    """One PAM access-grant lifecycle event.

    ``event`` is one of ``requested`` | ``approved`` | ``denied`` | ``revoked``.
    ``requester`` is only used for the ``requested`` event (sent to approvers).
    All link to the platform Access dashboard.
    """
    locale = _user_locale(user)
    # Every level asked for, named — one ask can be for two things, and a
    # message describing only the first would ask for a decision about
    # something it had not mentioned.
    level_label = ", ".join(
        email_t(LEVEL_LABEL_KEYS[level], locale=locale)
        for level in (levels or ())
        if level in LEVEL_LABEL_KEYS
    )
    base = f"accessGrant.{event}"
    return EmailPieces(
        subject=email_t(
            f"{base}.subject", locale=locale, guildName=guild_name, escape=False
        ),
        headline=email_t(f"{base}.title", locale=locale),
        body=email_t(
            f"{base}.body",
            locale=locale,
            guildName=guild_name,
            level=level_label,
            requester=requester or "",
        ),
        link=_frontend_url("/settings/operator/access"),
        link_label=email_t("accessGrant.buttonLabel", locale=locale),
    )


def initiative_join_request_pieces(
    user: User,
    *,
    event: str,
    initiative_name: str,
    requester: str | None = None,
    message: str | None = None,
) -> EmailPieces:
    """One initiative join-request lifecycle event.

    ``event`` is one of ``requested`` | ``approved`` | ``denied``. ``requester``
    and ``message`` belong to ``requested`` only — that one goes to the
    initiative's managers and carries what they need to decide; the other two go
    to the requester and carry the outcome.

    No link: these are guild-scoped, so the notice they ride on fills in its
    guild-aware smart link.
    """
    locale = _user_locale(user)
    base = f"initiativeJoinRequest.{event}"
    # The requester's note is their own free text. email_t escapes interpolated
    # values in the `email` namespace, so it lands in the HTML part as literal
    # text; the line is omitted entirely when they wrote nothing, rather than
    # rendering an empty quotation.
    note = (
        f"<br>{email_t(f'{base}.note', locale=locale, message=message)}"
        if message
        else ""
    )
    return EmailPieces(
        subject=email_t(
            f"{base}.subject",
            locale=locale,
            initiativeName=initiative_name,
            escape=False,
        ),
        headline=email_t(f"{base}.title", locale=locale),
        body=email_t(
            f"{base}.body",
            locale=locale,
            initiativeName=initiative_name,
            requester=requester or "",
        )
        + note,
        link_label=email_t(f"{base}.buttonLabel", locale=locale),
    )


def _redacted_item(text: str, link: str | None) -> str:
    """One digest line for a community that asks for redacted notifications.

    The kind of thing that happened, and the way back to it. Nothing in it
    comes from the content, so there is nothing here to escape.
    """
    return f'<li><a href="{link}">{text}</a></li>' if link else f"<li>{text}</li>"


def task_assignment_digest_pieces(
    user: User, assignments: Sequence[dict]
) -> EmailPieces:
    """The "these landed on you" summary, as one list."""
    locale = _user_locale(user)

    def assignment_html(item: dict) -> str:
        if item.get("redacted"):
            return _redacted_item(
                email_t("taskAssignment.redactedItem", locale=locale),
                item.get("link"),
            )
        # ``title`` is user-controlled and spliced into markup directly (not via
        # email_t), so escape it here.
        title = _html.escape(item.get("task_title") or "Task")
        project_name = item.get("project_name") or "a project"
        assigned_by = item.get("assigned_by_name")
        link = item.get("link")
        title_markup = (
            f'<a href="{link}"><strong>{title}</strong></a>'
            if link
            else f"<strong>{title}</strong>"
        )
        assigned_fragment = (
            f" ({email_t('taskAssignment.assignedBy', locale=locale, name=assigned_by)})"
            if assigned_by
            else ""
        )
        return f"<li>{title_markup} {email_t('taskAssignment.inProject', locale=locale, projectName=project_name)}{assigned_fragment}</li>"

    items_html = "".join(assignment_html(item) for item in assignments)
    return EmailPieces(
        subject=email_t("taskAssignment.subject", locale=locale, escape=False),
        headline=email_t("taskAssignment.title", locale=locale),
        body=(f"{email_t('taskAssignment.body', locale=locale)}<ul>{items_html}</ul>"),
    )


def reaction_digest_pieces(user: User, reactions: Sequence[dict]) -> EmailPieces:
    """The "people reacted to your posts" summary.

    Same shape as the assignment digest: one list, one line per reaction,
    linking back to what was reacted to.
    """
    locale = _user_locale(user)

    def reaction_html(item: dict) -> str:
        if item.get("redacted"):
            return _redacted_item(
                email_t("reaction.redactedItem", locale=locale), item.get("link")
            )
        # ``emoji`` and ``context_title`` are user-controlled and spliced into
        # markup directly (not via email_t), so escape them here.
        emoji = _html.escape(item.get("emoji") or "")
        context = _html.escape(item.get("context_title") or "")
        actor = item.get("reactor_name") or ""
        link = item.get("link")
        context_markup = (
            f'<a href="{link}"><strong>{context}</strong></a>'
            if link
            else f"<strong>{context}</strong>"
        )
        return (
            f"<li>{emoji} "
            f"{email_t('reaction.line', locale=locale, name=actor)} {context_markup}</li>"
        )

    items_html = "".join(reaction_html(item) for item in reactions)
    return EmailPieces(
        subject=email_t("reaction.subject", locale=locale, escape=False),
        headline=email_t("reaction.title", locale=locale),
        body=f"{email_t('reaction.body', locale=locale)}<ul>{items_html}</ul>",
    )


def direct_message_pieces(user: User, *, sender_name: str, link: str) -> EmailPieces:
    """Tell somebody a message is waiting, without telling them what it says.

    The subject and body carry the sender's name and nothing else. There is no
    preview here and no parameter that could carry one: the message this
    announces is encrypted, and the server has no key to it.
    """
    locale = _user_locale(user)
    return EmailPieces(
        subject=email_t("directMessage.subject", locale=locale, sender=sender_name),
        headline=email_t("directMessage.title", locale=locale),
        body=email_t("directMessage.body", locale=locale, sender=sender_name),
        link=link,
        link_label=email_t("directMessage.buttonLabel", locale=locale),
    )


def overdue_tasks_pieces(user: User, tasks: Sequence[dict]) -> EmailPieces:
    """What is past due, as one list."""
    locale = _user_locale(user)

    def overdue_html(item: dict) -> str:
        if item.get("redacted"):
            return _redacted_item(
                email_t("overdue.redactedItem", locale=locale), item.get("link")
            )
        # ``title`` is user-controlled and spliced into markup directly (not via
        # email_t), so escape it here.
        title = _html.escape(item.get("title") or "Task")
        project_name = item.get("project_name") or "a project"
        due_date = item.get("due_date") or "N/A"
        link = item.get("link")
        title_markup = (
            f'<a href="{link}"><strong>{title}</strong></a>'
            if link
            else f"<strong>{title}</strong>"
        )
        detail = email_t(
            "overdue.taskDetail",
            locale=locale,
            projectName=project_name,
            dueDate=due_date,
        )
        return f"<li>{title_markup} ({detail})</li>"

    items_html = "".join(overdue_html(item) for item in tasks)
    return EmailPieces(
        subject=email_t("overdue.subject", locale=locale, escape=False),
        headline=email_t("overdue.title", locale=locale),
        body=(
            f"{email_t('overdue.body', locale=locale, count=len(tasks))}"
            f"<ul>{items_html}</ul>"
        ),
    )
