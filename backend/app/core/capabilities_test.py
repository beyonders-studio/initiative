"""Unit tests for the platform capability model."""

import pytest

from app.core.capabilities import (
    Capability,
    can_assign_role,
    capabilities_for,
    roles_with_capability,
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
    ("capability", "holders"),
    [
        (Capability.CONFIG_MANAGE, {UserRole.owner}),
        (Capability.PLUGINS_MANAGE, {UserRole.owner}),
        (Capability.DATA_BYPASS, {UserRole.operator, UserRole.owner}),
        (Capability.ACCESS_APPROVE, {UserRole.operator, UserRole.owner}),
    ],
)
def test_the_rungs_holding_platform_authority(capability, holders):
    """Who may configure the deployment, break glass or approve access is
    policy: a change to it shows up here."""
    assert roles_with_capability(capability) == frozenset(holders)


def test_a_moderator_holds_moderation_alone():
    """A member holds nothing; a moderator moderates and asks for ``moderate``
    grants; support holds all of that plus recovery, billing and any grant."""
    assert capabilities_for(UserRole.member) == frozenset()
    moderator = capabilities_for(UserRole.moderator)
    support = capabilities_for(UserRole.support)
    assert {
        Capability.CONTENT_MODERATE,
        Capability.COMMUNITIES_SUSPEND,
        Capability.ACCESS_REQUEST,
    } <= moderator
    for capability in (
        Capability.ACCESS_REQUEST_ANY,
        Capability.USERS_MANAGE,
        Capability.USERS_AGE_UNBLOCK,
        Capability.BILLING_SUPPORT,
    ):
        assert capability not in moderator
        assert capability in support
    assert moderator < support


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
