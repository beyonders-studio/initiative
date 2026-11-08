"""Tests for transactional email rendering (HTML escaping)."""

import logging
import smtplib
from dataclasses import replace
from datetime import UTC
from types import SimpleNamespace

import pytest

from app.core.email_i18n import email_t
from app.services import email as email_service
from app.services.auth import addresses
from app.testing import create_user

EVIL_NAME = '<a href="https://phish.example">Reset your password</a>'


async def test_mention_email_escapes_malicious_display_name(session, monkeypatch):
    """A mention email whose actor display name contains markup must show the
    literal text in the HTML part (no live link inside the brand-styled body)
    while the plain-text alternative keeps the raw text."""
    user = await create_user(session)

    captured: dict = {}

    async def fake_send_email(
        _session, *, recipients, subject, html_body, text_body=None, settings_obj=None
    ):
        captured.update(
            recipients=recipients,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )

    monkeypatch.setattr(email_service, "send_email", fake_send_email)

    # Mirrors a file-mention notice: the actor name is interpolated via
    # email_t, which now escapes values for the email (HTML) namespace.
    body_text = email_t("mention.file.body", "en", actor=EVIL_NAME, file="Plans")
    html_body, text_body = email_service.render_single(
        email_service.EmailPieces(
            subject=email_t("mention.file.subject", "en", file="Plans", escape=False),
            headline=email_t("mention.file.title", "en"),
            body=body_text,
            link="https://app.example/files/1",
        ),
        user=user,
        accent="#000000",
        locale="en",
    )
    captured["subject"] = email_t(
        "mention.file.subject", "en", file="Plans", escape=False
    )
    captured["html_body"], captured["text_body"] = html_body, text_body

    # HTML part: markup neutralized to literal text; template <strong> intact.
    assert EVIL_NAME not in captured["html_body"]
    assert "&lt;a href=&quot;https://phish.example&quot;&gt;" in captured["html_body"]
    assert "<strong>" in captured["html_body"]
    # Plain-text part: the user's raw text, tags from the template stripped.
    assert EVIL_NAME in captured["text_body"]
    # Subject is a header, not HTML — never entity-encoded.
    assert captured["subject"] == "You were mentioned in Plans"


def test_strip_html_unescapes_entities():
    # The plain-text alternative is derived from the escaped HTML fragment, so
    # tags are stripped first and entities decoded back to literal text.
    assert (
        email_service._strip_html("<strong>Tom &amp; Jerry</strong> said &lt;hi&gt;")
        == "Tom & Jerry said <hi>"
    )


async def test_join_request_email_renders_and_escapes_the_note(session, monkeypatch):
    """The manager's copy resolves from the `initiativeJoinRequest` block and
    neutralizes the requester's free-text note in the HTML part.

    The note is the one piece of this mail the requester writes, and `email_t`
    returns the key itself when a template is missing — so this pins both that
    the keys exist and that the note renders as text, not markup, in the
    brand-styled body.
    """
    manager = await create_user(session)

    captured: dict = {}

    async def fake_send_email(
        _session, *, recipients, subject, html_body, text_body=None, settings_obj=None
    ):
        captured.update(
            recipients=recipients,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )

    monkeypatch.setattr(email_service, "send_email", fake_send_email)

    pieces = email_service.initiative_join_request_pieces(
        manager,
        event="requested",
        initiative_name="Parser Guild",
        requester="Ada Lovelace",
        message=EVIL_NAME,
    )
    # The notice it rides on fills in the link, as ``notifications.notify`` does.
    pieces = replace(
        pieces, link="https://app.example/navigate?community_id=1&target=%2Fi%2F2"
    )
    html_body, text_body = email_service.render_single(
        pieces, user=manager, accent="#000000", locale="en"
    )
    await email_service.deliver(
        session,
        manager,
        subject=pieces.subject,
        html_body=html_body,
        text_body=text_body,
    )
    captured["html_body"], captured["text_body"] = html_body, text_body

    assert captured["recipients"] == [
        await addresses.primary_address(session, user_id=manager.id)
    ]
    assert pieces.subject == "Request to join Parser Guild"
    # Templates resolved rather than falling through as their keys.
    assert "initiativeJoinRequest." not in captured["html_body"]
    assert "Ada Lovelace" in captured["html_body"]
    assert "Review the request" in captured["html_body"]
    # The note is present but inert in the HTML part, raw in the text part.
    assert EVIL_NAME not in captured["html_body"]
    assert "&lt;a href=&quot;https://phish.example&quot;&gt;" in captured["html_body"]
    assert EVIL_NAME in captured["text_body"]


@pytest.mark.parametrize(
    ("event", "subject"),
    [
        ("approved", "You've joined Parser Guild"),
        ("denied", "Request to join Parser Guild declined"),
    ],
)
async def test_join_request_outcome_emails_render(
    session, monkeypatch, event: str, subject: str
):
    """The requester's copy resolves for both outcomes, and omits the note line
    entirely when there is nothing to quote."""
    requester = await create_user(session)

    captured: dict = {}

    async def fake_send_email(
        _session, *, recipients, subject, html_body, text_body=None, settings_obj=None
    ):
        captured.update(subject=subject, html_body=html_body, text_body=text_body)

    monkeypatch.setattr(email_service, "send_email", fake_send_email)

    pieces = email_service.initiative_join_request_pieces(
        requester,
        event=event,
        initiative_name="Parser Guild",
    )
    pieces = replace(
        pieces, link="https://app.example/navigate?community_id=1&target=%2Fi"
    )
    html_body, text_body = email_service.render_single(
        pieces, user=requester, accent="#000000", locale="en"
    )
    captured.update(subject=pieces.subject, html_body=html_body, text_body=text_body)

    assert captured["subject"] == subject
    assert "initiativeJoinRequest." not in captured["html_body"]
    assert "Parser Guild" in captured["html_body"]
    assert "They wrote" not in captured["html_body"]


def test_the_hold_letter_names_the_deletion_day_when_there_is_one():
    from datetime import datetime

    day = datetime(2026, 10, 24, tzinfo=UTC)
    billed, held, undated = (
        email_service.community_on_hold_pieces(
            community="Acme",
            contact="help@example.com",
            guild_id=7,
            delete_at=delete_at,
            plan_managed=plan_managed,
            locale="en",
        )
        for delete_at, plan_managed in ((day, True), (day, False), (None, True))
    )

    assert "<strong>24 October 2026</strong> unless its plan is restored" in billed.body
    assert "help@example.com" in billed.body
    # Restoring the plan lifts the hold, so the letter leads to the portal.
    assert billed.link is not None
    assert billed.link.endswith("/c/7/billing?page=manage")
    assert billed.link_label == "Restore the plan"
    # Where no plan is behind the hold, the plan is not what lifts it.
    assert "unless the hold is lifted" in held.body
    assert "plan" not in held.body
    assert held.link is None
    assert "deleted" not in undated.body


def test_the_hold_letter_is_written_in_its_readers_language():
    from datetime import datetime

    letter = email_service.community_on_hold_pieces(
        community="Acme",
        contact=None,
        guild_id=7,
        delete_at=datetime(2026, 3, 4, tzinfo=UTC),
        plan_managed=True,
        locale="de",
    )

    assert letter.subject == "Acme ist pausiert"
    assert "am <strong>4. März 2026</strong> gelöscht" in letter.body
    assert letter.link_label == "Tarif wiederherstellen"


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("en", "8 October 2026"),
        ("de", "8. Oktober 2026"),
        ("es", "8 de octubre de 2026"),
        ("fr", "8 octobre 2026"),
        ("xx", "8 October 2026"),
    ],
)
def test_a_letter_writes_a_day_the_way_its_language_does(locale, expected):
    from datetime import date

    assert email_service.email_date(date(2026, 10, 8), locale) == expected


@pytest.mark.parametrize(
    "refusal, line",
    [
        (
            smtplib.SMTPDataError(554, b"rejected for someone@example.com"),
            "Failed to send email (SMTPDataError, code 554)",
        ),
        (
            smtplib.SMTPRecipientsRefused({"someone@example.com": (550, b"no")}),
            "Failed to send email (SMTPRecipientsRefused)",
        ),
    ],
)
async def test_a_refused_send_logs_its_type_and_code_and_raises_without_it(
    monkeypatch, caplog, refusal, line
):
    config = SimpleNamespace(from_address="initiative@example.com", password=None)

    async def no_password():
        return None

    def refuse(_config, _message):
        raise refusal

    monkeypatch.setattr(email_service, "_build_smtp_config", lambda _s: config)
    monkeypatch.setattr(email_service, "_smtp_password", no_password)
    monkeypatch.setattr(email_service, "_deliver", refuse)

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError) as raised:
        await email_service.send_email(
            None,
            recipients=["someone@example.com"],
            subject="Hello",
            html_body="<p>Hello</p>",
            settings_obj=SimpleNamespace(),
        )

    assert line in caplog.text
    assert "someone@example.com" not in caplog.text
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__
