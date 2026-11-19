"""Names of the objects rendered on a table: its triggers, indexes and
constraints.

Postgres keeps the first 63 bytes of an identifier and drops the rest without
an error, so two names that differ only after that are one name: the second
``CREATE OR REPLACE TRIGGER`` replaces the first. Every built-in table's names
fit. A tool plug-in's table is named from what its publisher declared
(``p_<uid>_<key>``) and can be long enough that they do not, so a name that
would not fit takes a digest of the table's name in its place.
"""

from __future__ import annotations

import hashlib

#: The longest identifier Postgres keeps whole, in bytes.
MAX_IDENTIFIER_LENGTH = 63


def object_name(prefix: str, table: str, suffix: str) -> str:
    """``<prefix>_<table>_<suffix>``, or ``<prefix>_<digest>_<suffix>`` when
    that would not fit; an empty ``suffix`` leaves its part out."""
    tail = f"_{suffix}" if suffix else ""
    name = f"{prefix}_{table}{tail}"
    if len(name.encode()) <= MAX_IDENTIFIER_LENGTH:
        return name
    digest = hashlib.sha256(table.encode()).hexdigest()[:16]
    shortened = f"{prefix}_{digest}{tail}"
    if len(shortened.encode()) > MAX_IDENTIFIER_LENGTH:
        raise ValueError(f"{shortened!r} is longer than an identifier can be")
    return shortened
