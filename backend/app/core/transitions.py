"""Changes that give a deployment's older clients time to catch up.

When a release changes something an installed client depends on, the old way
keeps working for a grace period and then stops. The clock is the deployment's
own: it starts the first time this deployment boots with the change (recorded
in ``app_settings.transitions``), so a deployment that skips releases still
gives its clients the whole window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class Transition:
    name: str
    grace: timedelta


#: The transitions this release is counting down. Empty is the normal state.
TRANSITIONS: tuple[Transition, ...] = ()
