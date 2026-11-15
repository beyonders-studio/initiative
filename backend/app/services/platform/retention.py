"""The windows a deleted account, a deleted community, a held community and a
deleted plug-in install wait out before the hourly sweep acts on them.

A window is a status on a row, the ``status_changed_at`` stamp written when the
row entered it, and how many days it lasts: the deployment rule that says so,
with the one beside it that says whether it runs at all (``app.core.rules``),
or a fixed length. :class:`RetentionWindow` answers from those three alone
when a row's window ends, which rows are due, and runs the sweep that takes
each due row in turn.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, and_, inspect
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.rules import RETENTION_WINDOWS
from app.db.request_context import Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityStatus, Guild
from app.models.platform.plugin_install import PluginInstall, PluginInstallStatus
from app.models.platform.user import User, UserStatus
from app.services.platform import rules
from app.services.platform.rules import Values

logger = logging.getLogger(__name__)


#: How long a deleted plug-in install is kept, and may be set back to any
#: other status, before it is uninstalled.
PLUGIN_INSTALL_DELETION_DAYS = 30


@dataclass(frozen=True)
class RetentionWindow[RowT: (User, Guild, PluginInstall)]:
    """One window: rows of ``model`` in ``status``, kept for the number of days
    the deployment's rule ``setting`` holds, or for ``fixed_days``."""

    #: What the sweep does to one row, for its log lines.
    action: str
    model: type[RowT]
    status: str
    setting: str | None = None
    fixed_days: int | None = None

    def days(self, deployment: Values | None = None) -> int | None:
        """The window's length: its fixed one, or the one in the deployment's
        rules (``rules.platform_values``), or None where nothing ends it."""
        if self.setting is None:
            return self.fixed_days
        if deployment is None or not deployment[RETENTION_WINDOWS[self.setting]]:
            return None
        return deployment[self.setting]

    def due(self, *, now: datetime, days: int) -> ColumnElement[bool]:
        """Rows whose window has run out by ``now``. A row with no stamp never
        compares as due."""
        return and_(
            col(self.model.status) == self.status,
            col(self.model.status_changed_at) <= now - timedelta(days=days),
        )

    def ends_at(self, row: RowT, deployment: Values | None = None) -> datetime | None:
        """When ``row``'s window ends, or None if it is not in this window or
        nothing ends it."""
        days = self.days(deployment)
        if days is None or row.status != self.status or row.status_changed_at is None:
            return None
        return row.status_changed_at + timedelta(days=days)

    async def sweep(
        self,
        session: AsyncSession,
        *,
        now: datetime,
        act: Callable[[AsyncSession, RowT, int], Awaitable[None]],
    ) -> int:
        """Run ``act`` on every row due by ``now``, oldest first. Returns how
        many it ran on.

        The window is read per sweep, so a change applies to the next pass.
        Each row is claimed on its own, ``FOR UPDATE SKIP LOCKED`` and asking
        again that it is due, and ``act`` commits the claiming transaction: a
        row another sweep holds is left to it, and one it has finished is no
        longer due. A row whose ``act`` fails is rolled back, logged and left
        for the next sweep, and the rows behind it still run.
        """
        await set_rls_context(session, Unattributed())
        days = self.days(
            None if self.setting is None else await rules.platform_values(session)
        )
        if days is None:
            return 0
        due = self.due(now=now, days=days)
        model = self.model
        key = inspect(model).primary_key
        # Each row's key, with its stamp so a one-column key reads as a row too.
        stamped = col(model.status_changed_at)
        row_ids = [
            tuple(row)[: len(key)]
            for row in await session.exec(
                select(*key, stamped).where(due).order_by(stamped.asc())
            )
        ]
        await session.commit()
        done = 0
        for row_id in row_ids:
            # Guild ids repeat across schemas, so nothing is carried between rows.
            session.expunge_all()
            try:
                await set_rls_context(session, Unattributed())
                row = (
                    await session.exec(
                        select(model)
                        .where(
                            *(
                                column == value
                                for column, value in zip(key, row_id, strict=True)
                            ),
                            due,
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).one_or_none()
                if row is None:
                    await session.commit()
                    continue
                await act(session, row, days)
            except Exception:
                await session.rollback()
                logger.exception(
                    "%s %s failed; left for the next sweep", self.action, row_id
                )
                continue
            done += 1
        if done:
            logger.info("%s: %d done", self.action, done)
        return done


ACCOUNT_DELETION = RetentionWindow(
    action="erasing account",
    model=User,
    status=UserStatus.deleted,
    setting="deleted_account_retention_days",
)
COMMUNITY_DELETION = RetentionWindow(
    action="destroying guild",
    model=Guild,
    status=CommunityStatus.deleted.value,
    setting="deleted_community_retention_days",
)
COMMUNITY_HOLD = RetentionWindow(
    action="deleting held guild",
    model=Guild,
    status=CommunityStatus.on_hold.value,
    setting="on_hold_community_deletion_days",
)
PLUGIN_INSTALL_DELETION = RetentionWindow(
    action="uninstalling deleted plug-in",
    model=PluginInstall,
    status=PluginInstallStatus.deleted.value,
    fixed_days=PLUGIN_INSTALL_DELETION_DAYS,
)
