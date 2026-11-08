"""Tier 2: dynamic sort/filter payloads never become SQL text.

The list endpoints build ORDER BY / WHERE from user-supplied field names and
values through :mod:`app.db.query`. The contract: a field name must
resolve to a mapped column object or be dropped (never spliced into SQL), and a
value must be bound as a parameter (never interpolated). These compile the
built statements and assert both — no database required, so they run fast and
stay stable.
"""

from __future__ import annotations

from sqlalchemy import Column, Integer, String, select
from sqlalchemy.orm import declarative_base

from app.db.query import apply_filters, apply_sorting
from app.schemas.query import FilterCondition, FilterOp

_Base = declarative_base()


class _Widget(_Base):
    __tablename__ = "widgets_injection_probe"
    id = Column(Integer, primary_key=True)
    name = Column(String)


_ALLOWED = {"id": _Widget.id, "name": _Widget.name}

# A field name / sort key that contains SQL syntax.
_INJECTION = "name); DROP TABLE widgets_injection_probe; --"


def _sql_with_literals(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def test_hostile_sort_field_is_dropped_not_interpolated():
    """An unknown sort field (allowlist path) is dropped, not emitted as SQL."""
    stmt = apply_sorting(
        select(_Widget), _Widget, sort_by=_INJECTION, allowed_fields=_ALLOWED
    )
    sql = _sql_with_literals(stmt)
    assert "DROP TABLE" not in sql
    assert "ORDER BY" not in sql  # nothing valid to sort by, no default given


def test_hostile_sort_field_dropped_without_allowlist():
    """The ``getattr(model, field)`` fallback resolves an unknown attribute to
    None, so an unknown field is dropped there too."""
    stmt = apply_sorting(select(_Widget), _Widget, sort_by=_INJECTION)
    assert "DROP TABLE" not in _sql_with_literals(stmt)


def test_valid_sort_applied_while_hostile_sibling_dropped():
    """A real field still sorts; the unknown sibling is silently dropped."""
    stmt = apply_sorting(
        select(_Widget),
        _Widget,
        sort_by=f"name,{_INJECTION}",
        sort_dir="asc,asc",
        allowed_fields=_ALLOWED,
    )
    sql = _sql_with_literals(stmt)
    assert "ORDER BY" in sql
    assert "DROP TABLE" not in sql


def test_ilike_filter_value_is_bound_not_interpolated():
    """An ILIKE search term is bound as a parameter — the payload appears as a
    bind value, never in the SQL text."""
    cond = FilterCondition(field="name", op=FilterOp.ilike, value=_INJECTION)
    stmt = apply_filters(select(_Widget), _Widget, [cond], allowed_fields=_ALLOWED)

    compiled = stmt.compile()  # default: parameters are bound, not inlined
    assert "DROP TABLE" not in str(compiled)
    # The wrapped ILIKE term is present only as a bound parameter value.
    assert f"%{_INJECTION}%" in compiled.params.values()


def test_eq_filter_on_unknown_field_is_dropped():
    """A comparison on a non-allowlisted field yields no WHERE clause rather
    than resolving an arbitrary attribute."""
    cond = FilterCondition(field=_INJECTION, op=FilterOp.eq, value="x")
    stmt = apply_filters(select(_Widget), _Widget, [cond], allowed_fields=_ALLOWED)
    assert "WHERE" not in _sql_with_literals(stmt)
