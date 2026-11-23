"""The registry has to stay total over ``NotificationType``.

A new notification type with no category would resolve to nothing, and the
delivery path would have to guess — so this fails CI instead.
"""

import pytest

from app.core.notification_categories import (
    ALL_CHANNELS,
    CATEGORY_SPECS,
    NotificationCategory,
)
from app.models.platform.notification import NotificationType

pytestmark = pytest.mark.always


def test_every_notification_type_has_exactly_one_category():
    covered = [
        notification_type
        for spec in CATEGORY_SPECS.values()
        for notification_type in spec.types
    ]
    assert set(covered) == set(NotificationType)
    # A type in two categories would resolve differently depending on which
    # was read first.
    assert len(covered) == len(set(covered))


def test_every_category_is_in_the_registry():
    assert set(CATEGORY_SPECS) == set(NotificationCategory)


def test_every_category_declares_a_default_for_every_channel():
    for category, spec in CATEGORY_SPECS.items():
        assert set(spec.defaults) == set(ALL_CHANNELS), category
        assert spec.mutable_channels <= set(ALL_CHANNELS), category
