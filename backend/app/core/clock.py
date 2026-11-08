"""The current instant, timezone-aware in UTC."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Now, in UTC. Tests freeze a module's clock by patching its ``utcnow``."""
    return datetime.now(UTC)
