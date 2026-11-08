from datetime import date
from typing import Literal

from pydantic import AliasChoices, ConfigDict, Field

from app.schemas.base import SanitizedBaseModel


class VelocityWeekData(SanitizedBaseModel):
    """Weekly velocity data showing tasks assigned vs completed."""

    week_start: date = Field(..., description="Start date of the week")
    assigned: int = Field(..., description="Number of tasks assigned to user this week")
    completed: int = Field(..., description="Number of tasks completed this week")


class HeatmapDayData(SanitizedBaseModel):
    """Daily activity data for heatmap visualization."""

    day: date = Field(..., description="Date of activity", serialization_alias="date")
    activity_count: int = Field(
        ..., description="Number of task activities on this date"
    )


class CommunityTaskBreakdown(SanitizedBaseModel):
    """Task completion breakdown by guild."""

    community_id: int = Field(
        ...,
        description="Guild ID",
        validation_alias=AliasChoices("community_id", "guild_id"),
    )
    community_name: str = Field(
        ...,
        description="Guild name",
        validation_alias=AliasChoices("community_name", "guild_name"),
    )
    completed_count: int = Field(
        ..., description="Number of completed tasks in this guild"
    )


class UserStatsResponse(SanitizedBaseModel):
    """Comprehensive user statistics response."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    streak: int = Field(
        ...,
        description="Current streak of consecutive work days (Mon-Fri) with task activity",
    )
    on_time_rate: float = Field(
        ...,
        ge=0,
        le=100,
        description="Percentage of completed tasks finished before due date",
    )
    avg_completion_days: float | None = Field(
        None,
        description="Average days from start_date to completion (only tasks with start_date)",
    )
    tasks_completed_total: int = Field(
        ..., description="Total number of completed tasks"
    )
    tasks_completed_this_week: int = Field(
        ..., description="Number of tasks completed this week"
    )
    backlog_trend: Literal["Growing", "Shrinking"] = Field(
        ..., description="Trend based on tasks assigned vs completed this week"
    )
    velocity_data: list[VelocityWeekData] = Field(
        ..., description="Weekly velocity data for last 12 weeks"
    )
    heatmap_data: list[HeatmapDayData] = Field(
        ..., description="Daily activity data for last 365 days"
    )
    community_breakdown: list[CommunityTaskBreakdown] = Field(
        ...,
        description="Task completion breakdown by guild",
        validation_alias=AliasChoices("community_breakdown", "guild_breakdown"),
    )
