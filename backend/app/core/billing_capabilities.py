"""What billing's capability names mean here.

Billing names what a plan includes as ``feature_keys``. Each name this build
knows is a paid switch in ``app.core.rules.COMMUNITY_RULES`` of the same name,
held as a deployment row while the plan includes it.
"""

from __future__ import annotations

from typing import Iterable

from app.core.rules import COMMUNITY_RULES, Slot

#: Every name this build understands: the paid switches. Used by the tests
#: that keep the two repositories' vocabularies in step; the boundary itself
#: ignores the rest.
KNOWN_CAPABILITIES: frozenset[str] = frozenset(
    key
    for key, rule in COMMUNITY_RULES.items()
    if rule.paid and rule.slot is Slot.enabled
)


def capability_values(package: Iterable[str]) -> dict[str, bool]:
    """The paid switches one package resolves to. Every switch this build
    knows is decided by the package, including the ones it does not mention:
    absence is withdrawal."""
    granted = set(package)
    return {key: key in granted for key in sorted(KNOWN_CAPABILITIES)}
