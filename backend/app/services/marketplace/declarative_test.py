"""A declarative endpoint, run as the SDK's ``runEndpoint`` runs it, and an
``after_connect`` as its ``runAfterConnect`` does.

The plug-in is the SDK's own test plug-in (``test/support/app.ts``, 1.4.0), and each
case asserts what its ``test/testing.test.ts`` asserts: the requests rendered,
in order, and what the run answered. The vendor is ``FakeVendor``'s API,
answering from recorded answers; the one difference from the SDK's rendered
requests is the credential, which only Initiative adds.
"""

from datetime import UTC, datetime

import pytest

from app.core.messages import PluginDataMessages
from app.services.marketplace.declarative import (
    after_connect,
    request_refusal,
    run_endpoint,
)
from app.services.marketplace.definitions import normalize_listing_definition
from app.services.marketplace.plugin_data import PluginDataError
from app.services.tenant.plugin_connection_flows import HookError
from app.testing.fake_vendor import FakeVendor

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
API = "https://api.tracker.example"
CREDENTIALS = {"workspace": "tok-workspace", "account": "tok-account"}
WORKSPACE = {"workspace": {"owner": "acme"}}
#: An install whose settings hold nothing, as every expression reads it.
INSTALLED = {"settings": {}, "aliases": {}}


def _api(path: str) -> str:
    return f'"{API}{path}"'


def issues_plugin(**changes) -> dict:
    """The SDK's ``issuesPlugin``, as Initiative stores it."""
    endpoints: dict[str, dict] = {
        "open-issues": {
            "direction": "read",
            "params": [
                {
                    "key": "state",
                    "type": "select",
                    "options": ["Open", "Closed"],
                    "label": {"en": "State"},
                }
            ],
            "returns": [
                {"key": "titles", "type": "string", "list": True},
                {"key": "total", "type": "int"},
            ],
            "request": {
                "method": "GET",
                "url": f'{_api("/repos/")} & connection.owner & "/issues"',
                "query": {
                    "state": "$lowercase(params.state)",
                    "labels": "params.labels",
                },
                "headers": {"Accept": '"application/json"'},
                "connection": "workspace",
                "paging": {
                    "kind": "page_number",
                    "page_param": "page",
                    "per_page_param": "per_page",
                    "per_page": 2,
                    "max_pages": 2,
                    "on_limit": "refuse",
                },
            },
            "map": '{"titles": response.body.title[], "total": $count(response.body)}',
        },
        "label": {
            "direction": "write",
            "returns": [{"key": "labels", "type": "string", "list": True}],
            "unavailable": ["locked"],
            "steps": [
                {
                    "name": "current",
                    "request": {
                        "method": "GET",
                        "url": f'{_api("/issues/")} & params.number & "/labels"',
                        "connection": "workspace",
                    },
                },
                {
                    "name": "set",
                    "request": {
                        "method": "PUT",
                        "url": f'{_api("/issues/")} & params.number & "/labels"',
                        "body": '{"labels": $append(steps.current.body.name, params.label)}',
                        "connection": "workspace",
                    },
                },
            ],
            "map": '{"labels": steps.set.body.name[]}',
            "errors": [
                {
                    "status": 422,
                    "when": 'response.body.message = "locked"',
                    "code": "locked",
                }
            ],
        },
        "search": {
            "direction": "read",
            # The SDK's test plug-in leaves this out; Initiative requires a member
            # connection a request uses to be named in requires.
            "requires": {"all_of": ["account"]},
            "returns": [{"key": "ids", "type": "string", "list": True}],
            "request": {
                "method": "POST",
                "url": _api("/graphql"),
                "graphql": {
                    "query": "query($after: String) { issues(after: $after) { nodes { id } } }",
                    "variables": '{"after": null}',
                },
                "connection": "account",
                "paging": {
                    "kind": "cursor",
                    "next": "response.body.data.issues.pageInfo.endCursor",
                    "more": "response.body.data.issues.pageInfo.hasNextPage",
                    "variable": "after",
                    "items": "response.body.data.issues.nodes",
                    "max_pages": 3,
                    "on_limit": "truncate",
                },
            },
            "map": '{"ids": response.body.id[]}',
        },
    }
    for name, change in changes.items():
        endpoints[name] = {**endpoints.get(name, {}), **change}
    return normalize_listing_definition(
        "plugin",
        {
            "plugin_kind": "service",
            "features": ["endpoints"],
            "hosts": ["api.tracker.example", "*.tracker.example"],
            "connections": [
                {
                    "id": "workspace",
                    "scope": "static",
                    "label": {"en": "Workspace"},
                    "fields": [
                        {"key": "owner", "type": "string", "label": {"en": "Owner"}}
                    ],
                },
                {
                    "id": "account",
                    "scope": "interactive",
                    "label": {"en": "Your account"},
                    "fields": [],
                    "flow": {
                        "type": "oauth2",
                        "authorize_url": "https://tracker.example/authorize",
                        "token_url": "https://tracker.example/token",
                        "client_id": "abc",
                    },
                },
            ],
            "endpoints": [
                {"id": f"plugin.acme.issues.{name}", **endpoint}
                for name, endpoint in endpoints.items()
            ],
        },
        public_id="acme.issues",
    )


@pytest.fixture
def vendor(monkeypatch) -> FakeVendor:
    vendor = FakeVendor(api_host="api.tracker.example")
    vendor.install(monkeypatch)
    return vendor


async def _run(
    name: str,
    *,
    params=None,
    definition=None,
    connections=WORKSPACE,
    installed=INSTALLED,
    actor=None,
) -> dict:
    definition = definition or issues_plugin()
    endpoint = next(
        entry for entry in definition["endpoints"] if entry["id"].endswith(f".{name}")
    )
    return await run_endpoint(
        definition,
        endpoint,
        params=params or {},
        connections=connections,
        credentials=CREDENTIALS,
        now=NOW,
        installed=installed,
        actor=actor,
    )


async def test_each_page_is_rendered_and_the_map_reads_every_pages_items(vendor):
    vendor.api_answers = [
        {"body": [{"title": "A"}, {"title": "B"}]},
        {"body": [{"title": "C"}]},
    ]
    result = await _run("open-issues", params={"state": "Open"})

    assert [request["url"] for request in vendor.api_requests] == [
        f"{API}/repos/acme/issues?state=open&page={page}&per_page=2" for page in (1, 2)
    ]
    first = vendor.api_requests[0]
    assert first["method"] == "GET"
    assert first["headers"]["accept"] == "application/json"
    assert first["headers"]["authorization"] == "Bearer tok-workspace"
    assert result == {"titles": ["A", "B", "C"], "total": 3}


async def test_a_range_past_max_pages_is_refused_when_on_limit_says_so(vendor):
    full = {"body": [{"title": "A"}, {"title": "B"}]}
    vendor.api_answers = [full, full]
    assert await _run("open-issues") == {"unavailable": "range-too-large"}


async def test_a_truncating_range_answers_the_pages_it_read(vendor):
    full = {"body": [{"title": "A"}, {"title": "B"}]}
    vendor.api_answers = [full, full]
    definition = issues_plugin(
        **{
            "open-issues": {
                "request": {
                    **issues_plugin()["endpoints"][0]["request"],
                    "paging": {
                        "kind": "page_number",
                        "page_param": "page",
                        "per_page": 2,
                        "max_pages": 2,
                        "on_limit": "truncate",
                    },
                }
            }
        }
    )
    result = await _run("open-issues", definition=definition)
    assert result == {"titles": ["A", "B", "A", "B"], "total": 4}
    assert vendor.api_requests[1]["url"] == f"{API}/repos/acme/issues?page=2"


async def test_steps_run_in_order_each_reading_the_ones_before_it(vendor):
    vendor.api_answers = [
        {"body": [{"name": "ui"}]},
        {"body": [{"name": "ui"}, {"name": "bug"}]},
    ]
    result = await _run("label", params={"number": 7, "label": "bug"})

    second = vendor.api_requests[1]
    assert (second["method"], second["url"]) == ("PUT", f"{API}/issues/7/labels")
    assert second["body"] == {"labels": ["ui", "bug"]}
    assert second["headers"]["content-type"] == "application/json"
    assert result == {"labels": ["ui", "bug"]}


#: An after_connect in steps: the installation, then the person's membership
#: of the account it is on.
STEPPED_AFTER_CONNECT = {
    "steps": [
        {
            "name": "installation",
            "request": {
                "method": "GET",
                "url": f"{_api('/installations/')} & params.installation_id",
            },
        },
        {
            "name": "member",
            "request": {
                "method": "GET",
                "url": f"{_api('/orgs/')} & steps.installation.body.account"
                ' & "/membership"',
            },
        },
    ],
    "map": '{"values": {"owner": steps.installation.body.account},'
    ' "account_label": steps.installation.body.account}',
    "refuse_when": 'response.body.role != "admin" or steps.member.body.role != "admin"',
    "code": "not-admin",
}


async def _after_connect(after: dict = STEPPED_AFTER_CONNECT):
    return await after_connect(
        issues_plugin(),
        after,
        params={"installation_id": "2"},
        access_token="tok-person",
        installed=INSTALLED,
        now=NOW,
    )


async def test_after_connect_steps_run_in_order_each_reading_the_ones_before_it(
    vendor,
):
    vendor.api_answers = [{"body": {"account": "acme"}}, {"body": {"role": "admin"}}]
    answer = await _after_connect()

    assert [request["url"] for request in vendor.api_requests] == [
        f"{API}/installations/2",
        f"{API}/orgs/acme/membership",
    ]
    assert all(
        request["headers"]["authorization"] == "Bearer tok-person"
        for request in vendor.api_requests
    )
    assert not answer.refused
    assert answer.values == {"owner": "acme"}
    assert answer.account_label == "acme"


async def test_after_connect_refuses_by_a_steps_answer(vendor):
    vendor.api_answers = [{"body": {"account": "acme"}}, {"body": {"role": "member"}}]
    answer = await _after_connect()
    assert (answer.refused, answer.code) == (True, "not-admin")


async def test_a_failing_after_connect_step_fails_the_hook(vendor):
    vendor.api_answers = [{"body": {"account": "acme"}}, {"status": 404}]
    with pytest.raises(HookError, match="not-found"):
        await _after_connect()


@pytest.mark.parametrize(
    "answer,answered",
    [
        ({"status": 422, "body": {"message": "locked"}}, "locked"),
        ({"status": 422, "body": {"message": "bad"}}, "invalid"),
        ({"status": 404}, "not-found"),
        ({"status": 403}, "not-authorized"),
        ({"status": 429}, None),
        ({"status": 502}, None),
    ],
)
async def test_an_answer_means_what_its_rule_or_the_default_says(
    vendor, answer, answered
):
    vendor.api_answers = [answer]
    if answered is None:
        with pytest.raises(PluginDataError) as refused:
            await _run("label", params={"number": 7})
        assert refused.value.code == PluginDataMessages.SERVICE_UNAVAILABLE
        assert refused.value.status_code == 502
    else:
        assert await _run("label", params={"number": 7}) == {"unavailable": answered}
    assert [request["method"] for request in vendor.api_requests] == ["GET"]


async def test_connections_holds_each_connection_requires_names(vendor):
    """A request on the member's connection reads the community's by id; a
    connection ``requires`` does not name is not there."""
    definition = issues_plugin(
        comment={
            "direction": "write",
            "requires": {"all_of": ["workspace", "account"]},
            "returns": [{"key": "id", "type": "int"}],
            "request": {
                "method": "POST",
                "url": f'{_api("/repos/")} & connections.workspace.owner & "/comments"',
                "body": '{"seen": connections, "login": connection.login}',
                "connection": "account",
            },
            "map": '{"id": response.body.id}',
        }
    )
    vendor.api_answers = [{"body": {"id": 9}}]
    result = await _run(
        "comment",
        definition=definition,
        connections={
            **WORKSPACE,
            "account": {"login": "alice"},
            "other": {"owner": "elsewhere"},
        },
    )

    sent = vendor.api_requests[0]
    assert sent["url"] == f"{API}/repos/acme/comments"
    assert sent["headers"]["authorization"] == "Bearer tok-account"
    assert sent["body"] == {
        "seen": {"workspace": {"owner": "acme"}, "account": {"login": "alice"}},
        "login": "alice",
    }
    assert result == {"id": 9}


def _label_per_actor() -> dict:
    """:func:`issues_plugin` with its label write made as the member, setting
    the labels on their own account, or as the installation, on the
    community's workspace."""
    current, put = issues_plugin()["endpoints"][1]["steps"]
    put["request"].update(
        body='{"labels": [params.label], "own": connection}',
        connection={"member": "account", "installation": "workspace"},
    )
    return issues_plugin(
        label={
            "actors": ["member", "installation"],
            "requires": {"all_of": ["workspace"]},
            "steps": [current, put],
        }
    )


@pytest.mark.parametrize(
    "actor,token,own",
    [
        ("installation", "tok-workspace", {"owner": "acme"}),
        ("member", "tok-account", {"login": "alice"}),
    ],
)
async def test_a_request_naming_a_connection_per_actor_carries_the_actors(
    vendor, actor, token, own
):
    """A call carries, and reads as ``connection``, the connection a request
    names for the actor it is made as; one named for every call, whoever
    makes it."""
    vendor.api_answers = [{"body": [{"name": "ui"}]}, {"body": [{"name": "bug"}]}]
    result = await _run(
        "label",
        params={"number": 7, "label": "bug"},
        definition=_label_per_actor(),
        connections={**WORKSPACE, "account": {"login": "alice"}},
        actor=actor,
    )

    current, put = vendor.api_requests
    assert current["headers"]["authorization"] == "Bearer tok-workspace"
    assert put["headers"]["authorization"] == f"Bearer {token}"
    assert put["body"] == {"labels": ["bug"], "own": own}
    assert result == {"labels": ["bug"]}


def test_a_call_made_as_no_actor_carries_no_connection_named_per_actor():
    """A request naming a connection per actor names none for a call made as
    no actor, which is refused before any token is asked for; a call made as
    the member needs the handle of the member's own."""
    definition = _label_per_actor()
    label = definition["endpoints"][1]
    assert [
        getattr(request_refusal(definition, label, refs, actor), "code", None)
        for actor, refs in (
            (None, {}),
            ("member", {}),
            ("member", {"account": "cr_member"}),
            ("installation", {}),
        )
    ] == [
        PluginDataMessages.NEEDS_CONFIGURATION,
        PluginDataMessages.CONNECTION_REQUIRED,
        None,
        None,
    ]


async def test_the_request_and_map_read_the_installs_settings(vendor):
    """Every expression reads the install's ``settings``, and each unique
    setting's earlier values as ``aliases``."""
    definition = issues_plugin(
        linked={
            "direction": "read",
            "returns": [{"key": "prefixes", "type": "string", "list": True}],
            "request": {
                "method": "GET",
                "url": _api("/search"),
                "query": {"q": 'settings.task_prefix & "-"'},
                "connection": "workspace",
            },
            "map": '{"prefixes": $append(settings.task_prefix, aliases.task_prefix)}',
        }
    )
    vendor.api_answers = [{"body": {}}]
    result = await _run(
        "linked",
        definition=definition,
        installed={
            "settings": {"task_prefix": "acme"},
            "aliases": {"task_prefix": ["acmeold"]},
        },
    )

    assert vendor.api_requests[0]["url"] == f"{API}/search?q=acme-"
    assert result == {"prefixes": ["acme", "acmeold"]}


async def test_a_graphql_cursor_is_sent_in_its_variable_from_the_second_page(vendor):
    def page(ids, more):
        return {
            "body": {
                "data": {
                    "issues": {
                        "nodes": [{"id": id_} for id_ in ids],
                        "pageInfo": {"endCursor": ids[-1], "hasNextPage": more},
                    }
                }
            }
        }

    vendor.api_answers = [page(["a"], True), page(["b"], False)]
    result = await _run("search")

    assert [request["body"]["variables"] for request in vendor.api_requests] == [
        {"after": None},
        {"after": "a"},
    ]
    assert vendor.api_requests[0]["headers"]["authorization"] == "Bearer tok-account"
    assert result == {"ids": ["a", "b"]}


async def test_a_link_header_is_followed_on_the_plugins_hosts_only(vendor):
    listing = {
        "request": {
            "method": "GET",
            "url": _api("/issues"),
            "connection": "workspace",
            "paging": {"kind": "link_header", "max_pages": 3, "on_limit": "truncate"},
        },
        "map": '{"titles": response.body.title[], "total": $count(response.body)}',
    }
    definition = issues_plugin(**{"open-issues": listing})
    vendor.api_answers = [
        {
            "headers": {"Link": f'<{API}/issues?page=2>; rel="next"'},
            "body": [{"title": "A"}],
        },
        {
            "headers": {"Link": '<https://elsewhere.example/more>; rel="next"'},
            "body": [{"title": "B"}],
        },
    ]
    result = await _run("open-issues", definition=definition)

    assert result == {"unavailable": "mapping-failed"}
    assert [request["url"] for request in vendor.api_requests] == [
        f"{API}/issues",
        f"{API}/issues?page=2",
    ]


@pytest.mark.parametrize(
    "url",
    [
        '"https://elsewhere.example/issues"',
        '"http://api.tracker.example/issues"',
        '"https://api.tracker.example:8443/issues"',
        '"https://deep.api.tracker.example/issues"',
        "42",
    ],
)
async def test_a_request_off_the_plugins_hosts_is_never_sent(vendor, url):
    definition = issues_plugin(
        **{
            "open-issues": {
                "request": {"method": "GET", "url": url, "connection": "workspace"},
            }
        }
    )
    assert await _run("open-issues", definition=definition) == {
        "unavailable": "mapping-failed"
    }
    assert vendor.api_requests == []


async def test_a_cursor_in_a_parameter_and_the_plugins_own_auth(vendor):
    definition = issues_plugin(
        **{
            "open-issues": {
                "request": {
                    "method": "GET",
                    "url": _api("/issues"),
                    "connection": "workspace",
                    "paging": {
                        "kind": "cursor",
                        "next": "response.body.next",
                        "more": "$exists(response.body.next)",
                        "param": "cursor",
                        "items": "response.body.items",
                        "max_pages": 3,
                        "on_limit": "truncate",
                    },
                },
            }
        }
    )
    definition["auth"] = {"header": "X-Tracker-Token", "prefix": ""}
    vendor.api_answers = [
        {"body": {"items": [{"title": "A"}], "next": "c 2"}},
        {"body": {"items": [{"title": "B"}]}},
    ]
    result = await _run("open-issues", definition=definition)

    assert [request["url"] for request in vendor.api_requests] == [
        f"{API}/issues",
        f"{API}/issues?cursor=c+2",
    ]
    assert vendor.api_requests[0]["headers"]["x-tracker-token"] == "tok-workspace"
    assert "authorization" not in vendor.api_requests[0]["headers"]
    assert result == {"titles": ["A", "B"], "total": 2}


@pytest.mark.parametrize(
    "mapping,answered",
    [
        ('{"titles": [1]}', "mapping-failed"),
        ('{"stranger": 1}', "mapping-failed"),
        ('{"unavailable": "locked"}', "mapping-failed"),
        ('{"unavailable": "not-found"}', "not-found"),
        ('$pad("", 1048577, "x")', "mapping-failed"),
    ],
    ids=["wrong-type", "undeclared", "undeclared-code", "platform-code", "too-large"],
)
async def test_a_map_answers_its_returns_or_a_code_of_its_own(
    vendor, mapping, answered
):
    """A map that does not fit the declared returns, names a code the endpoint
    does not have, or passes an expression bound answers mapping-failed."""
    vendor.api_answers = [{"body": []}]
    definition = issues_plugin(**{"open-issues": {"map": mapping}})
    assert await _run("open-issues", definition=definition) == {"unavailable": answered}
