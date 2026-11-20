"""Unit tests for the JSON-based translation loader."""

import pytest

from app.core.email_i18n import email_t, translate


def test_email_namespace_is_the_default_and_holds_rich_email_copy():
    assert translate("verification.subject", "en") == "Verify your Initiative account"
    # The email namespace carries subject + title + body for a notification.
    assert translate("event.invitation.subject", "en", event="Raid Night") == (
        "You're invited: Raid Night"
    )
    assert (
        translate(
            "event.invitation.body",
            "en",
            organizer="Ada",
            event="Raid Night",
            when="tonight",
        )
        == "<strong>Ada</strong> invited you to <strong>Raid Night</strong> (<strong>tonight</strong>)."
    )


def test_notifications_namespace_holds_terse_push_copy():
    # The notifications namespace carries only title + body, worded for push.
    assert (
        translate("event.invitation.title", "en", namespace="notifications")
        == "New event invitation"
    )
    assert (
        translate(
            "event.invitation.body",
            "en",
            namespace="notifications",
            event="Raid",
            when="8pm",
        )
        == "Raid (8pm)"
    )


def test_translate_localizes_per_locale():
    assert (
        translate("comment.reply.title", "es", namespace="notifications")
        == "Respuesta a tu comentario"
    )
    assert (
        translate(
            "mention.task.body",
            "fr",
            namespace="notifications",
            actor="Léa",
            task="Donjon",
            context="Quête",
        )
        == "Léa a mentionné Donjon dans Quête"
    )
    body = translate(
        "accessGrant.approved.body",
        "fr",
        namespace="notifications",
        guild="Guilde",
        level=translate("accessGrant.levelReadWrite", "fr", namespace="notifications"),
    )
    assert body == "Votre accès en lecture-écriture à Guilde a été approuvé"
    assert email_t("verification.subject", "fr") == "Vérifiez votre compte Initiative"


def test_translate_falls_back_to_english_for_untranslated_locale():
    # ``zz`` has no locale files at all, so it must fall back to English
    # rather than surfacing the raw key.
    assert (
        translate("event.reminder.title", "zz", namespace="notifications")
        == "Upcoming event"
    )


def test_translate_returns_key_when_missing_everywhere():
    assert translate("event.nope.missing", "en", namespace="notifications") == (
        "event.nope.missing"
    )


def test_plural_selection_uses_count():
    one = translate("overdue.body", "en", count=1)
    other = translate("overdue.body", "en", count=3)
    assert one == "You have <strong>1</strong> overdue task:"
    assert other == "You have <strong>3</strong> overdue tasks:"


# --- HTML escaping of interpolated values -------------------------------


def test_email_namespace_escapes_interpolated_values_by_default():
    # A display name containing markup must render as
    # literal text inside the HTML email body — the template's own <strong>
    # tags stay intact, only the substituted VALUE is escaped.
    body = translate(
        "event.invitation.body",
        "en",
        organizer='<a href="https://phish.example">Reset your password</a>',
        event="Raid Night",
        when="tonight",
    )
    assert (
        "&lt;a href=&quot;https://phish.example&quot;&gt;Reset your password&lt;/a&gt;"
        in body
    )
    assert '<a href="https://phish.example">' not in body
    assert body.startswith("<strong>")  # template markup untouched


def test_email_namespace_escape_false_keeps_values_raw():
    # Plain-text contexts (subjects, textBody) opt out per call.
    assert (
        translate(
            "event.invitation.subject", "en", event="Tom & Jerry <night>", escape=False
        )
        == "You're invited: Tom & Jerry <night>"
    )


def test_notifications_namespace_is_not_escaped_by_default():
    # Push copy is plain text rendered by the OS, never HTML.
    assert (
        translate(
            "event.invitation.body",
            "en",
            namespace="notifications",
            event="Tom & Jerry",
            when="8pm",
        )
        == "Tom & Jerry (8pm)"
    )


@pytest.mark.parametrize("locale", ["en", "de", "es", "fr"])
def test_every_category_has_a_digest_heading(locale: str):
    """A digest groups by category, so a category with no heading would print
    its own key at somebody. The registry is the list; this is the check that
    the four locales keep up with it."""
    from app.core.notification_categories import NotificationCategory

    for category in NotificationCategory:
        key = f"digest.category.{category.value}"
        assert email_t(key, locale=locale) != key, (
            f"{locale}/email.json is missing {key}"
        )


@pytest.mark.parametrize("locale", ["en", "de", "es", "fr"])
def test_every_reason_a_digest_goes_out_has_copy(locale: str):
    for reason in ("hourly", "daily", "weekly", "away", "recent"):
        assert email_t(f"digest.{reason}.title", locale=locale) != (
            f"digest.{reason}.title"
        )
        subject = email_t(f"digest.{reason}.subject", locale=locale, count=2)
        assert subject != f"digest.{reason}.subject"
        assert "2" in subject
