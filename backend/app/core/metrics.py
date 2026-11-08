"""What this process measures, for Prometheus to read.

The metric objects live here and nothing else does. The request edge
(:mod:`app.core.request_audit`) records requests and sockets, the engines
(:mod:`app.db.session`) record statements, and ``/api/v1/metrics`` on the
health router answers the scrape.

Labels are route templates, methods, status codes, engine names and account or
community statuses — never a community or a person, so a series never names
who it is about.

Every series is per process. A deployment running several replicas is
scraped once per replica: request and statement series add up across them
with ``sum``, while the platform totals — the same count read by each — are
taken with ``max``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Mapping

from prometheus_client import REGISTRY, Counter, Gauge, Histogram, Info
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import QueuePool

from app.core.version import get_version

#: Seconds, from a cached lookup to a page nobody should have waited for.
_REQUEST_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
#: Seconds, finer at the bottom, where most statements land.
_STATEMENT_BUCKETS = (
    0.001,
    0.0025,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
)

#: The route label of a request no route answered. The path itself would be a
#: new series for every path anybody typed.
UNMATCHED_ROUTE = "unmatched"

#: The methods a request is labelled by; anything else is ``other``.
METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})

http_requests = Counter(
    "initiative_http_requests",
    "HTTP requests answered, by route template and status.",
    ("method", "route", "status"),
)
http_request_duration = Histogram(
    "initiative_http_request_duration_seconds",
    "Time from a request arriving to its response finishing.",
    ("method", "route"),
    buckets=_REQUEST_BUCKETS,
)
http_requests_in_progress = Gauge(
    "initiative_http_requests_in_progress",
    "HTTP requests being answered right now.",
    ("method",),
)
websocket_connections = Gauge(
    "initiative_websocket_connections",
    "Live connections (notifications, collaboration, counters) open now.",
)
db_statement_duration = Histogram(
    "initiative_db_statement_duration_seconds",
    "Time each database statement took, by engine.",
    ("engine",),
    buckets=_STATEMENT_BUCKETS,
)
db_slow_statements = Counter(
    "initiative_db_slow_statements",
    "Statements over the slow threshold; each is also a warning in the log.",
    ("engine",),
)
db_cross_cohort_routes = Counter(
    "initiative_db_cross_cohort_routes",
    "Times a pooled connection was routed into a community outside its "
    "cohort, by the cohort (or platform pool) the connection belongs to.",
    ("cohort",),
)
plugin_hook_deliveries = Counter(
    "initiative_plugin_hook_deliveries",
    "Vendor webhook deliveries received for plug-ins, by outcome: refused (the "
    "signature did not verify), unroutable (no community connected it), "
    "delivered, or failed (a community's plug-in did not accept it).",
    ("outcome",),
)
db_connection_communities = Histogram(
    "initiative_db_connection_communities",
    "Communities a pooled connection served before it closed, by cohort.",
    ("cohort",),
    buckets=(1, 2, 5, 10, 25, 50, 100, 250, 500, 1000),
)
sweep_pass_duration = Histogram(
    "initiative_sweep_pass_duration_seconds",
    "Time a background pass over the communities took, by pass.",
    ("pass",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)
sweep_timer_lag = Histogram(
    "initiative_sweep_timer_lag_seconds",
    "How long past its due time a sweep timer was claimed, by sweep.",
    ("sweep",),
    buckets=(1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 900.0, 3600.0),
)
sweep_timer_repairs = Counter(
    "initiative_sweep_timer_repairs",
    "Sweep timers the daily reconcile armed because no write had, by sweep.",
    ("sweep",),
)
users = Gauge(
    "initiative_users",
    "Accounts on this deployment, by status.",
    ("status",),
)
guilds = Gauge(
    "initiative_guilds",
    "Communities on this deployment, by status.",
    ("status",),
)
sessions_active = Gauge(
    "initiative_sessions_active",
    "Signed-in sessions that have neither expired nor been signed out.",
)
active_users = Gauge(
    "initiative_active_users",
    "Accounts that were active within each window.",
    ("window",),
)
tools_created = Counter(
    "initiative_tools_created",
    "Tools created, by kind.",
    ("tool",),
)
page_views = Counter(
    "initiative_page_views",
    "Pages opened in the app, by route template.",
    ("route",),
)
Info("initiative_build", "The release this process is running.").info(
    {"version": get_version()}
)


#: The windows active accounts are counted over, by label, in days.
ACTIVE_WINDOWS: dict[str, int] = {"1d": 1, "7d": 7, "30d": 30}

#: The SPA's route templates, the only values the page view ``route`` label
#: takes. Kept in step with the router by ``frontend/src/pageRoutes.test.ts``.
PAGE_ROUTES: frozenset[str] = frozenset(
    json.loads(Path(__file__).with_name("page_routes.json").read_text())
)

#: The ``route`` label of a page view for a template not in the list.
OTHER_PAGE = "other"


def method_label(method: str | None) -> str:
    return method if method in METHODS else "other"


def record_page_view(route: str) -> None:
    page_views.labels(route=route if route in PAGE_ROUTES else OTHER_PAGE).inc()


def record_platform_totals(
    *,
    users_by_status: Mapping[str, int],
    guilds_by_status: Mapping[str, int],
    live_sessions: int,
    active_by_window: Mapping[str, int],
) -> None:
    """Replace the platform totals with a fresh count.

    Cleared first, so a status nobody holds any more stops being reported
    rather than keeping its last value.
    """
    users.clear()
    for status, count in users_by_status.items():
        users.labels(status=status).set(count)
    guilds.clear()
    for status, count in guilds_by_status.items():
        guilds.labels(status=status).set(count)
    sessions_active.set(live_sessions)
    for window, count in active_by_window.items():
        active_users.labels(window=window).set(count)


#: The engines whose pools are reported, by the label they are reported under.
_watched_engines: dict[str, AsyncEngine] = {}


def watch_pool(label: str, engine: AsyncEngine) -> None:
    """Report this engine's connection pool on every scrape.

    The engine is held rather than its pool, because disposing an engine
    replaces the pool.
    """
    _watched_engines[label] = engine


class _PoolCollector(Collector):
    """Each watched pool's connections, read when Prometheus asks."""

    def collect(self) -> Iterator[GaugeMetricFamily]:
        family = GaugeMetricFamily(
            "initiative_db_pool_connections",
            "Connections in each engine's pool: checked out, idle, or beyond "
            "the pool's size.",
            labels=("engine", "state"),
        )
        for label, engine in _watched_engines.items():
            pool = engine.pool
            # Only a queue pool keeps these counts; a pool that opens a
            # connection per use has nothing to report.
            if not isinstance(pool, QueuePool):
                continue
            family.add_metric((label, "checked_out"), pool.checkedout())
            family.add_metric((label, "idle"), pool.checkedin())
            family.add_metric((label, "overflow"), max(pool.overflow(), 0))
        yield family


REGISTRY.register(_PoolCollector())
