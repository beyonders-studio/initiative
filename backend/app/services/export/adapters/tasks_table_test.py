"""Unit tests for tasks-table adapter helpers."""

from types import SimpleNamespace


from app.services.export.adapters.tasks_table import _thread_comments


def _c(id: int, parent: int | None = None):
    return SimpleNamespace(id=id, parent_comment_id=parent)


def test_thread_comments_nests_replies_under_parents():
    # Chronological input: root A, root B, reply to A, reply to that reply.
    a, b, a_reply, a_reply_reply = _c(1), _c(2), _c(3, 1), _c(4, 3)
    ordered = _thread_comments([a, b, a_reply, a_reply_reply])
    # A, then its reply subtree (depth 1, 2), then root B — not flat order.
    assert [(c.id, d) for c, d in ordered] == [(1, 0), (3, 1), (4, 2), (2, 0)]


def test_thread_comments_preserves_order_within_a_level():
    a, r1, r2 = _c(1), _c(2, 1), _c(3, 1)
    ordered = _thread_comments([a, r1, r2])
    assert [c.id for c, _ in ordered] == [1, 2, 3]  # replies in input order


def test_thread_comments_treats_orphans_as_roots():
    """A reply whose parent isn't in the set (parent deleted / not loaded) is
    kept as a root so nothing is dropped."""
    orphan = _c(5, 99)
    ordered = _thread_comments([orphan])
    assert [(c.id, d) for c, d in ordered] == [(5, 0)]


def test_thread_comments_handles_a_very_deep_chain_without_recursion():
    """A long single reply chain (each replying to the previous) must not blow
    Python's recursion limit — the walk is an explicit-stack DFS."""
    chain = [_c(1)]
    for i in range(2, 3001):
        chain.append(_c(i, i - 1))  # each replies to its predecessor
    ordered = _thread_comments(chain)
    assert len(ordered) == 3000
    assert ordered[0] == (chain[0], 0)
    assert ordered[-1][0].id == 3000
    assert ordered[-1][1] == 2999  # depth grows with the chain


def test_every_task_layout_field_says_how_it_exports():
    """A field a task's layout can show has an entry, a way to write it or
    ``None`` to leave it out, so a new one cannot quietly miss exports."""
    from app.schemas.tenant.tool_layout import TaskFieldId
    from app.services.export.adapters.tasks_table import TASK_EXPORT_FIELDS

    assert set(TaskFieldId) <= TASK_EXPORT_FIELDS.keys()
