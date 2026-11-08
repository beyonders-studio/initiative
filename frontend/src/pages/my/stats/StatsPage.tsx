import type { LucideIcon } from "lucide-react";
import { Clock, Flame, Target, TrendingDown, TrendingUp } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useCommunities } from "@/hooks/useCommunities";
import { useUserStats } from "@/hooks/useUserStats";
import { Alert, AlertDescription } from "@/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { cn } from "@/ui/lib/utils";
import { CardGridSkeleton, ContentCardSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

import { CommunityBreakdownChart } from "./CommunityBreakdownChart";
import { HeatmapChart } from "./HeatmapChart";
import { VelocityChart } from "./VelocityChart";

interface StatsMetricCardProps {
  icon: LucideIcon;
  title: string;
  value: number | string | null;
  unit?: string;
  subtitle?: string;
  variant?: "default" | "success" | "warning" | "danger";
}

function StatsMetricCard({
  icon: Icon,
  title,
  value,
  unit,
  subtitle,
  variant = "default",
}: StatsMetricCardProps) {
  const displayValue = value ?? "N/A";

  const variantStyles = {
    default: "text-foreground",
    success: "text-green-600 dark:text-green-400",
    warning: "text-yellow-600 dark:text-yellow-400",
    danger: "text-red-600 dark:text-red-400",
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="font-medium text-sm">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className={cn("font-bold text-2xl", variantStyles[variant])}>
          {displayValue}
          {unit && value !== null && (
            <span className="ml-1 text-muted-foreground text-sm">{unit}</span>
          )}
        </div>
        {subtitle && <p className="mt-1 text-muted-foreground text-xs">{subtitle}</p>}
      </CardContent>
    </Card>
  );
}

const COMMUNITY_FILTER_ALL = "all";

export function StatsPage() {
  const { t } = useTranslation("stats");
  const [selectedCommunityId, setSelectedCommunityId] = useState<string>(COMMUNITY_FILTER_ALL);
  const { communities } = useCommunities();

  const communityIdParam =
    selectedCommunityId === COMMUNITY_FILTER_ALL ? null : Number(selectedCommunityId);
  const { data: stats, isLoading, error } = useUserStats(communityIdParam);

  const handleCommunityChange = (value: string) => {
    setSelectedCommunityId(value);
  };

  return (
    <div className="space-y-6">
      {/* Header with Community filter */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="font-semibold text-3xl tracking-tight">{t("page.title")}</h1>
        <div className="w-full sm:w-[200px]">
          <Select value={selectedCommunityId} onValueChange={handleCommunityChange}>
            <SelectTrigger>
              <SelectValue placeholder={t("page.communityFilterPlaceholder")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={COMMUNITY_FILTER_ALL}>{t("page.allCommunities")}</SelectItem>
              {communities.map((community) => (
                <SelectItem key={community.id} value={String(community.id)}>
                  {community.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Loading state */}
      {isLoading && (
        <SkeletonRegion className="space-y-6">
          <CardGridSkeleton count={4} className="grid grid-cols-fill-48/4 gap-4" />
          <ContentCardSkeleton lines={3} />
        </SkeletonRegion>
      )}

      {/* Error state */}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{t("page.error")}</AlertDescription>
        </Alert>
      )}

      {/* Stats content */}
      {stats && (
        <>
          {/* Top Metrics Row - 4 cards */}
          <div className="grid grid-cols-fill-48/4 gap-4">
            <StatsMetricCard
              icon={Flame}
              title={t("metrics.currentStreak")}
              value={stats.streak}
              unit={t("metrics.days")}
              subtitle={t("metrics.consecutiveDays")}
              variant={stats.streak >= 7 ? "success" : stats.streak >= 3 ? "warning" : "default"}
            />
            <StatsMetricCard
              icon={Target}
              title={t("metrics.onTimeRate")}
              value={stats.on_time_rate.toFixed(1)}
              unit="%"
              subtitle={t("metrics.onTimeSubtitle")}
              variant={
                stats.on_time_rate >= 80
                  ? "success"
                  : stats.on_time_rate >= 60
                    ? "warning"
                    : "danger"
              }
            />
            <StatsMetricCard
              icon={Clock}
              title={t("metrics.avgCompletion")}
              value={stats.avg_completion_days?.toFixed(1) ?? null}
              unit={stats.avg_completion_days !== null ? t("metrics.days") : undefined}
              subtitle={t("metrics.avgCompletionSubtitle")}
            />
            <StatsMetricCard
              icon={stats.backlog_trend === "Growing" ? TrendingUp : TrendingDown}
              title={t("metrics.backlogTrend")}
              value={
                stats.backlog_trend === "Growing" ? t("metrics.growing") : t("metrics.shrinking")
              }
              subtitle={t("metrics.thisWeek")}
              variant={stats.backlog_trend === "Shrinking" ? "success" : "warning"}
            />
          </div>

          {/* Tasks Completed Card */}
          <Card>
            <CardHeader>
              <CardTitle>{t("tasksCompleted.title")}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col gap-6 sm:flex-row sm:gap-12">
                <div>
                  <div className="font-bold text-3xl">{stats.tasks_completed_total}</div>
                  <div className="mt-1 text-muted-foreground text-sm">
                    {t("tasksCompleted.allTime")}
                  </div>
                </div>
                <div>
                  <div className="font-bold text-3xl">{stats.tasks_completed_this_week}</div>
                  <div className="mt-1 text-muted-foreground text-sm">
                    {t("tasksCompleted.thisWeek")}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Charts Row */}
          <div className="grid grid-cols-pair gap-6">
            <VelocityChart data={stats.velocity_data} />
            <CommunityBreakdownChart data={stats.community_breakdown} />
          </div>

          {/* Heatmap Full Width */}
          <HeatmapChart data={stats.heatmap_data} />
        </>
      )}
    </div>
  );
}
