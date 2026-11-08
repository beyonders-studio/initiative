"""Reading somebody else's site: what we ask it, and what we do when it
answers badly.

Egress is stubbed at ``request_public_target`` — the same seam the AI and
webhook paths are tested through. What matters here is the *shape* of the
conversation (which paths, which auth, which method) and that every way a
foreign server can misbehave becomes a code rather than prose.
"""

import base64
import io
from datetime import UTC

import httpx
import pytest

from app.core.messages import ImportEngineMessages
from app.services.import_engine import atlassian
from app.services.import_engine.contract import ImportEngineError

CREDENTIAL = atlassian.AtlassianCredential(
    site_url="https://acme.atlassian.net",
    email="someone@example.com",
    api_token="shhh",
)


@pytest.fixture(autouse=True)
def waits(monkeypatch) -> list[float]:
    """Every retry wait, recorded rather than slept."""
    recorded: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(atlassian, "_sleep", fake_sleep)
    return recorded


def _response(status_code: int, payload=None, *, text: str | None = None):
    if text is not None:
        return httpx.Response(status_code, text=text)
    return httpx.Response(status_code, json=payload if payload is not None else {})


async def answered(
    method: str, url: str, response: httpx.Response, kw: dict
) -> httpx.Response:
    """``response`` as ``request_public_target`` hands one back for the
    keyword arguments ``kw`` it was called with: bounded, and its body written
    to the sink when there is one."""
    from app.services.safe_http import _read_bounded

    if kw.get("max_bytes") is None:
        return response
    response.request = httpx.Request(method, url)
    return await _read_bounded(response, kw["max_bytes"], kw.get("sink"))


async def _download(path: str, **kw) -> bytes:
    """What :func:`atlassian.get_file` writes for ``path``, read back."""
    target = io.BytesIO()
    size = await atlassian.get_file(CREDENTIAL, path, target, **kw)
    assert size == len(target.getvalue())
    return target.getvalue()


def _stub(monkeypatch, handler):
    """Answer every outbound call with ``handler(method, url, json)``."""
    calls: list[dict] = []

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        calls.append({"method": method, "url": url, "headers": headers, "json": json})
        return await answered(method, url, handler(method, url, json), kw)

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    return calls


# --- the address -----------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://acme.atlassian.net", "https://acme.atlassian.net"),
        ("acme.atlassian.net", "https://acme.atlassian.net"),
        ("https://acme.atlassian.net/", "https://acme.atlassian.net"),
        # What a person actually pastes: a board, deep inside one product.
        (
            "https://acme.atlassian.net/jira/software/projects/ACME/boards/3",
            "https://acme.atlassian.net",
        ),
        ("  https://acme.atlassian.net  ", "https://acme.atlassian.net"),
        # A port is part of the address.
        ("https://acme.example.com:8443/wiki", "https://acme.example.com:8443"),
    ],
)
def test_a_site_is_read_down_to_its_host(raw, expected):
    assert atlassian.normalize_site_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "http://acme.atlassian.net", "https://"])
def test_a_site_we_cannot_call_is_refused(raw):
    """No scheme-less nonsense, and no http: the token would go in the clear,
    which is not a thing to support for a credential somebody typed."""
    with pytest.raises(ImportEngineError) as exc:
        atlassian.normalize_site_url(raw)
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE


# --- one call --------------------------------------------------------------


async def test_the_token_travels_as_basic_auth(monkeypatch):
    calls = _stub(monkeypatch, lambda m, u, j: _response(200, {"ok": True}))
    await atlassian.get_json(CREDENTIAL, "/rest/api/3/myself")

    expected = base64.b64encode(b"someone@example.com:shhh").decode()
    assert calls[0]["headers"]["Authorization"] == f"Basic {expected}"
    assert calls[0]["url"] == "https://acme.atlassian.net/rest/api/3/myself"


@pytest.mark.parametrize(
    "status_code,code",
    [
        (401, ImportEngineMessages.IMPORT_SOURCE_AUTH),
        (403, ImportEngineMessages.IMPORT_SOURCE_AUTH),
        (429, ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED),
        (500, ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE),
        (404, ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE),
    ],
)
async def test_every_refusal_becomes_a_code(monkeypatch, status_code, code):
    _stub(monkeypatch, lambda m, u, j: _response(status_code))
    with pytest.raises(ImportEngineError) as exc:
        await atlassian.get_json(CREDENTIAL, "/rest/api/3/myself")
    assert exc.value.code == code


async def test_a_body_that_is_not_json_is_not_an_answer(monkeypatch):
    """A proxy's error page comes back 200 with HTML in it. That is the
    network talking, not Atlassian."""
    _stub(monkeypatch, lambda m, u, j: _response(200, text="<html>nope</html>"))
    with pytest.raises(ImportEngineError) as exc:
        await atlassian.get_json(CREDENTIAL, "/rest/api/3/myself")
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE


async def test_a_private_address_is_refused_not_fetched(monkeypatch):
    from app.services.webhook_target_url import WebhookTargetUrlPrivateError

    async def fake_request(*a, **kw):
        raise WebhookTargetUrlPrivateError("private")

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    with pytest.raises(ImportEngineError) as exc:
        await atlassian.get_json(CREDENTIAL, "/rest/api/3/myself")
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_PRIVATE_HOST


async def test_a_site_that_will_not_answer_is_unreachable(monkeypatch):
    async def fake_request(*a, **kw):
        raise httpx.ConnectTimeout("too slow")

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    with pytest.raises(ImportEngineError) as exc:
        await atlassian.get_json(CREDENTIAL, "/rest/api/3/myself")
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE


# --- looking around --------------------------------------------------------


def _site(*, projects=None, spaces=None, jira_status=200, confluence_status=200):
    """A site that answers the four calls a probe makes."""

    def handler(method, url, json):
        if "/rest/api/3/project/search" in url:
            if jira_status != 200:
                return _response(jira_status)
            return _response(200, {"values": projects or []})
        if "/rest/api/3/search/approximate-count" in url:
            return _response(200, {"count": 42})
        if "/wiki/api/v2/spaces" in url:
            if confluence_status != 200:
                return _response(confluence_status)
            return _response(200, {"results": spaces or []})
        if "/wiki/rest/api/search" in url:
            return _response(200, {"totalSize": 7})
        return _response(404)

    return handler


async def test_a_probe_lists_both_products_with_their_counts(monkeypatch):
    calls = _stub(
        monkeypatch,
        _site(
            projects=[{"id": "1", "key": "ACME", "name": "Acme Board"}],
            spaces=[{"id": "9", "key": "DOCS", "name": "Docs"}],
        ),
    )
    jira, confluence = await atlassian.probe_site(CREDENTIAL)

    assert jira.available and confluence.available
    assert [(p.key, p.issue_count) for p in jira.projects] == [("ACME", 42)]
    assert [(s.key, s.page_count) for s in confluence.spaces] == [("DOCS", 7)]
    # The count is asked for as a POST, which is how the surviving Jira search
    # API takes a JQL.
    counts = [c for c in calls if "approximate-count" in c["url"]]
    assert counts and counts[0]["method"] == "POST"
    assert counts[0]["json"] == {"jql": 'project = "ACME"'}


async def test_a_site_with_only_one_product_still_connects(monkeypatch):
    """Plenty of sites run Jira and no Confluence. That is not a failure, and
    it must not stop somebody importing the product they do have."""
    _stub(
        monkeypatch,
        _site(
            projects=[{"id": "1", "key": "ACME", "name": "Acme"}],
            confluence_status=404,
        ),
    )
    jira, confluence = await atlassian.probe_site(CREDENTIAL)

    assert jira.available
    assert not confluence.available
    assert confluence.reason == ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE
    assert confluence.spaces == []


async def test_a_rejected_token_fails_the_whole_probe(monkeypatch):
    """Unlike a missing product, a token the site will not take is the
    person's problem to fix — the wizard has to say so rather than show an
    empty list."""
    _stub(monkeypatch, _site(jira_status=401))
    with pytest.raises(ImportEngineError) as exc:
        await atlassian.probe_site(CREDENTIAL)
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_AUTH


async def test_a_site_with_neither_product_is_the_wrong_address(monkeypatch):
    _stub(monkeypatch, _site(jira_status=404, confluence_status=404))
    with pytest.raises(ImportEngineError) as exc:
        await atlassian.probe_site(CREDENTIAL)
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE


async def test_one_unreadable_project_does_not_fail_the_probe(monkeypatch):
    """A count is a convenience. A project that will not answer reports no
    number rather than taking the whole site down with it."""

    def handler(method, url, json):
        if "/rest/api/3/project/search" in url:
            return _response(
                200,
                {
                    "values": [
                        {"id": "1", "key": "OK", "name": "Fine"},
                        {"id": "2", "key": "BAD", "name": "Locked"},
                    ]
                },
            )
        if "/rest/api/3/search/approximate-count" in url:
            if json and "BAD" in json.get("jql", ""):
                return _response(500)
            return _response(200, {"count": 3})
        if "/wiki/api/v2/spaces" in url:
            return _response(200, {"results": []})
        return _response(404)

    _stub(monkeypatch, handler)
    jira, _ = await atlassian.probe_site(CREDENTIAL)
    assert [(p.key, p.issue_count) for p in jira.projects] == [("OK", 3), ("BAD", None)]


async def test_a_huge_site_is_cut_rather_than_refused(monkeypatch):
    """One connect must not become a thousand outbound calls. The listing is
    capped, and only the first page of it is counted."""
    many = [{"id": str(i), "key": f"P{i}", "name": f"Project {i}"} for i in range(400)]
    calls = _stub(monkeypatch, _site(projects=many))
    jira, _ = await atlassian.probe_site(CREDENTIAL)

    assert len(jira.projects) == atlassian.MAX_PROBE_ENTRIES
    counted = [p for p in jira.projects if p.issue_count is not None]
    assert len(counted) == atlassian.MAX_COUNTED_ENTRIES
    assert len([c for c in calls if "approximate-count" in c["url"]]) == (
        atlassian.MAX_COUNTED_ENTRIES
    )


# --- being throttled ---------------------------------------------------------


def _throttled(retry_after: str | None = None):
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return httpx.Response(429, json={}, headers=headers)


def _sequence(*responses):
    """Answer each call with the next response, repeating the last."""
    queue = list(responses)

    def handler(m, u, j):
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return handler


async def test_a_throttled_call_waits_as_asked_and_tries_again(monkeypatch, waits):
    """The site said when to come back; the call waits at least that long —
    jitter only ever adds — and the retry's answer is the call's answer."""
    calls = _stub(monkeypatch, _sequence(_throttled("2"), _response(200, {"ok": True})))

    assert await atlassian.get_json(CREDENTIAL, "/rest/api/3/myself") == {"ok": True}
    assert len(calls) == 2
    assert len(waits) == 1
    assert 2.0 <= waits[0] <= 2.0 * (1 + atlassian.JITTER_FRACTION)


async def test_without_retry_after_the_waits_double(monkeypatch, waits):
    """No header: back off exponentially, and give up after the policy's
    attempts with the rate-limit code."""
    calls = _stub(monkeypatch, lambda m, u, j: _throttled())

    with pytest.raises(ImportEngineError) as exc:
        await atlassian.get_json(CREDENTIAL, "/rest/api/3/myself")

    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED
    assert len(calls) == atlassian.BACKGROUND.attempts
    # One wait between each pair of attempts, none after the last.
    assert len(waits) == atlassian.BACKGROUND.attempts - 1
    for attempt, wait in enumerate(waits):
        floor = atlassian.BACKOFF_BASE_SECONDS * 2**attempt
        assert floor <= wait <= floor * (1 + atlassian.JITTER_FRACTION)


async def test_a_wait_longer_than_the_policy_allows_is_a_block(monkeypatch, waits):
    """Told to come back in ten minutes is not a pause worth sleeping
    through: give up at once rather than hold the worker."""
    calls = _stub(monkeypatch, lambda m, u, j: _throttled("600"))

    with pytest.raises(ImportEngineError) as exc:
        await atlassian.get_json(CREDENTIAL, "/rest/api/3/myself")

    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED
    assert len(calls) == 1
    assert waits == []


async def test_retry_after_may_be_a_date(monkeypatch, waits):
    """The header's other form. A date in the past means "now"."""
    from datetime import datetime, timedelta
    from email.utils import format_datetime

    soon = format_datetime(datetime.now(UTC) + timedelta(seconds=3))
    _stub(monkeypatch, _sequence(_throttled(soon), _response(200, {})))
    await atlassian.get_json(CREDENTIAL, "/rest/api/3/myself")
    assert 0.0 < waits[0] <= 3.0 * (1 + atlassian.JITTER_FRACTION)

    waits.clear()
    past = format_datetime(datetime.now(UTC) - timedelta(minutes=5))
    _stub(monkeypatch, _sequence(_throttled(past), _response(200, {})))
    await atlassian.get_json(CREDENTIAL, "/rest/api/3/myself")
    assert waits == [0.0]


async def test_a_retry_after_that_is_nonsense_falls_back_to_backoff(monkeypatch, waits):
    _stub(monkeypatch, _sequence(_throttled("soon-ish"), _response(200, {})))
    await atlassian.get_json(CREDENTIAL, "/rest/api/3/myself")
    base = atlassian.BACKOFF_BASE_SECONDS
    assert base <= waits[0] <= base * (1 + atlassian.JITTER_FRACTION)


async def test_only_throttling_is_retried(monkeypatch, waits):
    """Every other failure is an answer; asking again gets the same one."""
    calls = _stub(monkeypatch, lambda m, u, j: _response(500))
    with pytest.raises(ImportEngineError):
        await atlassian.get_json(CREDENTIAL, "/rest/api/3/myself")
    assert len(calls) == 1
    assert waits == []


async def test_the_probe_waits_briefly_because_someone_is_watching(monkeypatch, waits):
    """The connect step answers a person in the wizard, so it retries under
    the short policy: fewer attempts, and a long Retry-After is not waited
    out at all."""
    calls = _stub(monkeypatch, lambda m, u, j: _throttled())
    probe = await atlassian.probe_jira(CREDENTIAL)

    assert probe.available is False
    assert probe.reason == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED
    assert len(calls) == atlassian.INTERACTIVE.attempts

    calls.clear()
    waits.clear()
    _stub(monkeypatch, lambda m, u, j: _throttled("30"))
    await atlassian.probe_jira(CREDENTIAL)
    assert waits == []


# --- downloading a file ------------------------------------------------------


async def test_a_file_arrives_with_the_retry_a_json_call_gets(monkeypatch, waits):
    calls = _stub(
        monkeypatch,
        _sequence(_throttled("1"), httpx.Response(200, content=b"\x89PNG")),
    )
    data = await _download("/rest/api/3/attachment/content/10", max_bytes=100)
    assert data == b"\x89PNG"
    assert len(calls) == 2 and len(waits) == 1
    assert calls[0]["headers"]["Accept"] == "*/*"


async def test_a_file_bigger_than_its_bound_is_refused(monkeypatch):
    _stub(monkeypatch, lambda m, u, j: httpx.Response(200, content=b"x" * 101))
    with pytest.raises(ImportEngineError) as exc:
        await _download("/f", max_bytes=100)
    assert exc.value.code == ImportEngineMessages.IMPORT_TOO_LARGE


@pytest.mark.parametrize(
    "status_code,code",
    [
        (303, ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE),
        (404, ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE),
        (403, ImportEngineMessages.IMPORT_SOURCE_AUTH),
    ],
)
async def test_a_file_the_site_will_not_hand_over_is_a_code(
    monkeypatch, status_code, code
):
    """A redirect is not followed: the content endpoint is asked for the
    bytes directly, and a hop elsewhere is not an answer."""
    _stub(monkeypatch, lambda m, u, j: httpx.Response(status_code, content=b""))
    with pytest.raises(ImportEngineError) as exc:
        await _download("/f", max_bytes=100)
    assert exc.value.code == code


MEDIA = "https://api.media.atlassian.com/file/abc/binary?token=grant"


async def test_a_download_follows_its_one_hop_without_the_token(monkeypatch):
    calls = _stub(
        monkeypatch,
        lambda m, u, j: (
            httpx.Response(302, headers={"location": MEDIA})
            if "acme.atlassian.net" in u
            else httpx.Response(200, content=b"%PDF")
        ),
    )
    data = await _download("/wiki/download", max_bytes=100, follow_redirect=True)
    assert data == b"%PDF"
    assert [c["url"] for c in calls] == [
        "https://acme.atlassian.net/wiki/download",
        MEDIA,
    ]
    # The site's token goes to the site, and nowhere else.
    assert "Authorization" in calls[0]["headers"]
    assert "Authorization" not in calls[1]["headers"]


async def test_a_hop_that_is_not_https_is_not_followed(monkeypatch):
    calls = _stub(
        monkeypatch,
        lambda m, u, j: httpx.Response(
            302, headers={"location": "http://media.example.com/f"}
        ),
    )
    with pytest.raises(ImportEngineError) as exc:
        await _download("/wiki/download", max_bytes=100, follow_redirect=True)
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE
    assert len(calls) == 1


async def test_a_hop_to_a_private_address_is_refused(monkeypatch):
    from app.services.webhook_target_url import WebhookTargetUrlPrivateError

    async def fake_request(method, url, **kw):
        if url == MEDIA:
            raise WebhookTargetUrlPrivateError("private")
        return httpx.Response(302, headers={"location": MEDIA})

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    with pytest.raises(ImportEngineError) as exc:
        await _download("/wiki/download", max_bytes=100, follow_redirect=True)
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_PRIVATE_HOST


async def test_a_second_hop_is_not_followed(monkeypatch):
    _stub(
        monkeypatch,
        lambda m, u, j: httpx.Response(302, headers={"location": MEDIA}),
    )
    with pytest.raises(ImportEngineError) as exc:
        await _download("/wiki/download", max_bytes=100, follow_redirect=True)
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE


# --- how long a call may take ------------------------------------------------


def _slow(monkeypatch, seconds: float):
    """A site that takes ``seconds`` to finish every answer."""
    import asyncio

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        await asyncio.sleep(seconds)
        return await answered(method, url, _response(200, {"ok": True}, text=None), kw)

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)


async def test_a_call_that_does_not_finish_in_time_is_the_site_unreachable(
    monkeypatch,
):
    """Each read of the answer has its own timeout; the answer as a whole has
    a deadline too, so a site sending a byte at a time still ends."""
    _slow(monkeypatch, 0.5)
    with pytest.raises(ImportEngineError) as exc:
        await atlassian.get_json(
            CREDENTIAL,
            "/rest/api/3/myself",
            retry=atlassian.RetryPolicy(
                attempts=1, max_wait_seconds=0, call_deadline_seconds=0.05
            ),
        )
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE


async def test_a_download_gets_longer_the_larger_it_may_be(monkeypatch):
    _slow(monkeypatch, 0.2)
    monkeypatch.setattr(atlassian, "DOWNLOAD_FLOOR_BYTES_PER_SECOND", 1000)
    policy = atlassian.RetryPolicy(
        attempts=1, max_wait_seconds=0, call_deadline_seconds=0.05
    )
    # 1,000 bytes at 1,000 a second: a second on top of the call's own.
    data = await _download(
        "/rest/api/3/attachment/content/1", max_bytes=1000, retry=policy
    )
    assert data
    with pytest.raises(ImportEngineError) as exc:
        await _download("/rest/api/3/attachment/content/1", max_bytes=10, retry=policy)
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE


async def test_a_heartbeat_beats_at_most_once_per_interval(monkeypatch):
    beats: list[int] = []

    async def beat() -> None:
        beats.append(1)

    monkeypatch.setattr(atlassian, "HEARTBEAT_SECONDS", 3600)
    tick = atlassian.throttled(beat)
    for _ in range(5):
        await tick()
    assert beats == []

    monkeypatch.setattr(atlassian, "HEARTBEAT_SECONDS", 0)
    for _ in range(3):
        await tick()
    assert beats == [1, 1, 1]

    await atlassian.throttled(None)()
