"""What a credential is, read without the database."""

import uuid
from datetime import UTC, datetime, timedelta

from app.core.identify import HEADER_CREDENTIALS, URL_CREDENTIALS, identify_token
from app.core.messages import AuthMessages
from app.core.plugin_access_token import seal_install_token
from app.core.security import create_upload_token, mint_access_token


def _session_token(*, now: datetime | None = None) -> str:
    token, _ = mint_access_token(
        subject="ref-1",
        token_version=0,
        session_id=uuid.uuid4(),
        amr=["pwd"],
        satisfied_providers=[],
        now=now,
    )
    return token


def test_a_session_token_carries_its_claims():
    identified = identify_token(_session_token(), HEADER_CREDENTIALS, bearer=True)
    assert identified.refused is None
    assert identified.session is not None and identified.session.sub == "ref-1"


def test_an_expired_session_token_is_refused():
    expired = _session_token(now=datetime.now(UTC) - timedelta(days=1))
    assert (
        identify_token(expired, HEADER_CREDENTIALS).refused
        == AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS
    )


def test_a_token_with_another_audience_is_refused_where_it_is_not_allowed():
    upload, _ = create_upload_token(user_id=9)
    assert identify_token(upload, URL_CREDENTIALS).upload.user_id == 9
    assert (
        identify_token(upload, HEADER_CREDENTIALS).refused
        == AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS
    )
    assert (
        identify_token(_session_token(), URL_CREDENTIALS).refused
        == AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS
    )


def test_an_installed_plugins_token_is_unsealed_or_refused():
    token, _ = seal_install_token(
        guild_id=7,
        install_id=3,
        client_id="acme.widgets",
        scopes=frozenset(),
        initiative_id=None,
    )
    assert (
        identify_token(token, HEADER_CREDENTIALS, bearer=True).plugin_token is not None
    )
    tampered = identify_token(token[:-4] + "AAAA", HEADER_CREDENTIALS, bearer=True)
    assert tampered.refused == AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS
    assert tampered.plugin_token is None


def test_an_api_key_is_left_to_the_database():
    identified = identify_token("ppk_abc123", HEADER_CREDENTIALS)
    assert (
        identified.session,
        identified.upload,
        identified.access,
        identified.refused,
        identified.limit_key,
    ) == (None, None, None, None, None)
