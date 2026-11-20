"""Unit tests for the platform capability model."""

import pytest

from app.core.capabilities import (
    Capability,
    can_assign_role,
    capabilities_for,
    standing_capabilities,
    user_has_capability,
)
from app.models.platform.user import UserRole, UserStatus

pytestmark = pytest.mark.always


class _Actor:
    def __init__(self, role: UserRole, status: UserStatus = UserStatus.active):
        self.role = role
        self.status = status


def test_a_suspended_account_holds_no_capability():
    """Whatever its rung: it is in time out, and the rung comes back on lifting."""
    for role in UserRole:
        assert standing_capabilities(role, UserStatus.suspended) == frozenset()
        assert standing_capabilities(role, UserStatus.active) == capabilities_for(role)
    assert not user_has_capability(
        _Actor(UserRole.owner, UserStatus.suspended), Capability.CONFIG_MANAGE
    )


@pytest.mark.parametrize(
    ("actor", "assignable"),
    [
        (UserRole.owner, set(UserRole)),
        (UserRole.operator, set(UserRole) - {UserRole.owner}),
        (UserRole.support, set()),
        (UserRole.moderator, set()),
        (UserRole.member, set()),
    ],
)
def test_a_role_is_assigned_only_at_or_below_the_assigners_rung(actor, assignable):
    assert {
        role for role in UserRole if can_assign_role(_Actor(actor), role)
    } == assignable
