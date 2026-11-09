"""JSONata, evaluated as the SDK evaluates it.

The corpus is shared with the SDK by construction: each expected answer is what
``initiative-plugin-sdk``'s own ``evaluate`` (``src/expression.ts``, 1.4.0) gives
for the same expression and document at the same instant. The SDK ships no
corpus of its own, so it is kept here: the expressions of its
``test/testing.test.ts`` plug-in (``test/support/app.ts``), with the documents its
cases feed them, and the reshaping the GitHub and Shopify inventories need.
"""

import time

import pytest

from app.services.marketplace import expressions
from app.services.marketplace.expressions import UNDEFINED, ExpressionError

#: The instant every case is evaluated at, 2026-10-02T12:00:00.000Z.
MILLIS = 1790942400000

CORPUS = [
    (
        '"https://api.tracker.example/repos/" & connection.owner & "/issues"',
        {
            "params": {"state": "Open"},
            "connection": {"owner": "acme"},
            "now": "2026-10-02T12:00:00.000Z",
        },
        "https://api.tracker.example/repos/acme/issues",
    ),
    ("$lowercase(params.state)", {"params": {"state": "Open"}}, "open"),
    ("params.labels", {"params": {"state": "Open"}}, UNDEFINED),
    ('"application/json"', {}, "application/json"),
    (
        '{"titles": response.body.title[], "total": $count(response.body)}',
        {
            "response": {
                "status": 200,
                "headers": {},
                "body": [{"title": "A"}, {"title": "B"}, {"title": "C"}],
            }
        },
        {"titles": ["A", "B", "C"], "total": 3},
    ),
    (
        '{"titles": response.body.title[], "total": $count(response.body)}',
        {"response": {"status": 200, "headers": {}, "body": [{"title": "A"}]}},
        {"titles": ["A"], "total": 1},
    ),
    (
        '{"titles": response.body.title[], "total": $count(response.body)}',
        {"response": {"status": 200, "headers": {}, "body": []}},
        {"total": 0},
    ),
    (
        '"https://api.tracker.example/issues/" & params.number & "/labels"',
        {"params": {"number": 7, "label": "bug"}},
        "https://api.tracker.example/issues/7/labels",
    ),
    (
        '{"labels": $append(steps.current.body.name, params.label)}',
        {
            "params": {"number": 7, "label": "bug"},
            "steps": {
                "current": {"status": 200, "headers": {}, "body": [{"name": "ui"}]}
            },
        },
        {"labels": ["ui", "bug"]},
    ),
    (
        '{"labels": steps.set.body.name[]}',
        {
            "steps": {
                "set": {
                    "status": 200,
                    "headers": {},
                    "body": [{"name": "ui"}, {"name": "bug"}],
                }
            }
        },
        {"labels": ["ui", "bug"]},
    ),
    (
        'response.body.message = "locked"',
        {"response": {"status": 422, "headers": {}, "body": {"message": "locked"}}},
        True,
    ),
    (
        'response.body.message = "locked"',
        {"response": {"status": 422, "headers": {}}},
        False,
    ),
    ('{"after": null}', {}, {"after": None}),
    (
        "response.body.data.issues.pageInfo.endCursor",
        {
            "response": {
                "body": {
                    "data": {
                        "issues": {
                            "nodes": [{"id": "a"}],
                            "pageInfo": {"endCursor": "a", "hasNextPage": True},
                        }
                    }
                }
            }
        },
        "a",
    ),
    (
        "response.body.data.issues.nodes",
        {
            "response": {
                "body": {
                    "data": {
                        "issues": {
                            "nodes": [{"id": "a"}],
                            "pageInfo": {"endCursor": "a", "hasNextPage": True},
                        }
                    }
                }
            }
        },
        [{"id": "a"}],
    ),
    (
        '{"ids": response.body.id[]}',
        {"response": {"body": [{"id": "a"}, {"id": "b"}]}},
        {"ids": ["a", "b"]},
    ),
    (
        '($found := response.body[id = $$.params.installation_id]; {"values": {"owner": $found.account}, "account_label": $found.account})',
        {
            "params": {"installation_id": "2"},
            "response": {
                "body": [
                    {"id": "1", "account": "other"},
                    {"id": "2", "account": "acme"},
                ]
            },
        },
        {"values": {"owner": "acme"}, "account_label": "acme"},
    ),
    (
        '($found := response.body[id = $$.params.installation_id]; {"values": {"owner": $found.account}, "account_label": $found.account})',
        {
            "params": {"installation_id": "9"},
            "response": {"body": [{"id": "1", "account": "other"}]},
        },
        {"values": {}},
    ),
    ("$not($exists(result.values.owner))", {"result": {"values": {}}}, True),
    (
        'response.body.reason = "suspended"',
        {"response": {"status": 403, "body": {"reason": "suspended"}}},
        True,
    ),
    (
        'headers."x-event" = "issues" and payload.action = "opened"',
        {"headers": {"x-event": "issues"}, "payload": {"action": "opened"}},
        True,
    ),
    (
        '{"number": payload.issue.number, "title": payload.issue.title}',
        {"payload": {"issue": {"number": 7, "title": "Broken"}}},
        {"number": 7, "title": "Broken"},
    ),
    ("[$now(), $millis()]", {}, ["2026-10-02T12:00:00.000Z", 1790942400000]),
    ('$fromMillis($millis() - 7 * 86400000, "[Y0001]-[M01]-[D01]")', {}, "2026-09-25"),
    (
        "$toMillis(now) - 86400000 * params.since_days",
        {"now": "2026-10-02T12:00:00.000Z", "params": {"since_days": 3}},
        1790683200000,
    ),
    (
        'params.state = "all" ? null : $uppercase(params.state)',
        {"params": {"state": "all"}},
        None,
    ),
    (
        'params.state = "all" ? null : $uppercase(params.state)',
        {"params": {"state": "open"}},
        "OPEN",
    ),
    (
        "$sum(response.body.orders.$round($number(price) * 100))",
        {
            "response": {
                "body": {
                    "orders": [{"price": "19.99"}, {"price": "0.10"}, {"price": "5"}]
                }
            }
        },
        2509,
    ),
    (
        "response.body.items{status: $count($)}",
        {
            "response": {
                "body": {
                    "items": [
                        {"status": "open"},
                        {"status": "closed"},
                        {"status": "open"},
                    ]
                }
            }
        },
        {"open": 2, "closed": 1},
    ),
    (
        '$map([0..6], function($d) { $fromMillis($toMillis(now) - $d * 86400000, "[Y0001]-[M01]-[D01]") })',
        {"now": "2026-10-02T12:00:00.000Z"},
        [
            "2026-10-02",
            "2026-10-01",
            "2026-09-30",
            "2026-09-29",
            "2026-09-28",
            "2026-09-27",
            "2026-09-26",
        ],
    ),
    (
        '"repo:" & params.repo & (params.label ? " label:\\"" & params.label & "\\"" : "")',
        {"params": {"repo": "acme/web", "label": "good first issue"}},
        'repo:acme/web label:"good first issue"',
    ),
    ("$max([1, $min([params.limit, 50])])", {"params": {"limit": 120}}, 50),
    (
        "$filter(response.body, function($v) { $v.draft = false }).number",
        {
            "response": {
                "body": [
                    {"number": 1, "draft": False},
                    {"number": 2, "draft": True},
                    {"number": 3, "draft": False},
                ]
            }
        },
        [1, 3],
    ),
    (
        "response.body ~> $sort(function($a, $b) { $a.n > $b.n })",
        {"response": {"body": [{"n": 3}, {"n": 1}, {"n": 2}]}},
        [{"n": 1}, {"n": 2}, {"n": 3}],
    ),
    ('$string({"a": 1, "b": [true, null]})', {}, '{"a":1,"b":[true,null]}'),
    (
        '$join(response.body.labels.name, ", ")',
        {"response": {"body": {"labels": [{"name": "bug"}, {"name": "ui"}]}}},
        "bug, ui",
    ),
    (
        '$substringBefore(response.headers.link, ";")',
        {"response": {"headers": {"link": '<https://x/2>; rel="next"'}}},
        "<https://x/2>",
    ),
    ("$boolean(response.body.more)", {"response": {"body": {"more": "yes"}}}, True),
    ("$exists(response.body.next)", {"response": {"body": {}}}, False),
    ("$type(response.body)", {"response": {"body": None}}, "null"),
    ("10 / 4", {}, 2.5),
    ("2.5 * 2", {}, 5),
    ("nothing", {}, UNDEFINED),
]


@pytest.mark.parametrize("expression,document,expected", CORPUS)
async def test_an_expression_answers_what_the_sdk_answers(
    expression, document, expected
):
    assert await expressions.evaluate(expression, document, millis=MILLIS) == expected


@pytest.mark.parametrize(
    "expression,why,transient",
    [
        ("($f := function($n) { $f($n + 1) + 1 }; $f(0))", "Stack overflow", False),
        (f'$pad("", {expressions.OUTPUT_BYTES}, "x")', "over 1048576 bytes", False),
        # Slow but small: one large range runs out of memory before time.
        (
            "$sum([1..3000].($sum([1..3000])))",
            "timeout after 1000 milliseconds",
            True,
        ),
        ('$pad("", 2000000000, "x")', "ran out of memory", True),
    ],
    ids=["depth", "output", "time", "memory"],
)
async def test_an_evaluation_is_bounded(expression, why, transient):
    """Running out of time or memory may not happen again; the other bounds
    are the expression's own."""
    with pytest.raises(ExpressionError, match=why) as refused:
        await expressions.evaluate(expression, {})
    assert refused.value.transient is transient


async def test_a_step_that_never_yields_is_stopped():
    """One step the library cannot interrupt, a backtracking regular
    expression, is stopped with its worker, and the next evaluation runs on a
    fresh one."""
    started = time.monotonic()
    with pytest.raises(ExpressionError, match="timeout") as refused:
        await expressions.evaluate(
            '$match("a" & $pad("", 40, "a") & "!", /(a+)+$/)', {}
        )
    assert refused.value.transient
    assert time.monotonic() - started < expressions.TIME_MS / 1000 + 2
    assert await expressions.evaluate("1 + 1", {}) == 2


async def test_a_predicate_holds_by_jsonatas_boolean():
    assert await expressions.holds(
        "response.body.more", {"response": {"body": {"more": [0, 1]}}}
    )
    assert not await expressions.holds("response.body.more", {"response": {"body": {}}})
    assert not await expressions.holds('""', {})


def test_parsing_names_the_place_and_the_steps_read():
    with pytest.raises(ExpressionError) as refused:
        expressions.parse('{"a": ')
    assert refused.value.position is not None
    tree = expressions.parse('{"x": steps.first.body, "y": $$.steps.second.id}')
    assert expressions.step_reads(tree) == {"first", "second"}
    assert expressions.step_reads(expressions.parse("response.body.steps")) == set()
