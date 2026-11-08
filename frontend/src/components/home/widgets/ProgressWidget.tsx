/**
 * How the reader's work is going, at a glance: the streak, the week, how much
 * lands on time. The numbers My Stats opens with, for somebody who wants them
 * every morning rather than now and then.
 */

import type { LucideIcon } from "lucide-react";
import { CheckCheck, Flame, Target, Trophy } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { HomeWidgetCard, HomeWidgetNotice } from "@/components/home/HomeWidgetCard";
import { useUserStats } from "@/hooks/useUserStats";
import { numberFormat } from "@/ui/lib/intl";
import { Skeleton } from "@/ui/skeleton";
import { StatusMessage } from "@/ui/status-message";

const Stat = ({
  icon: Icon,
  label,
  children,
}: {
  icon: LucideIcon;
  label: string;
  children: ReactNode;
}) => (
  <div className="flex min-w-0 items-center gap-3 rounded-lg bg-muted/50 p-3">
    <Icon className="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
    <div className="min-w-0">
      <p className="font-bold text-xl leading-tight">{children}</p>
      <p className="truncate text-muted-foreground text-xs">{label}</p>
    </div>
  </div>
);

export const ProgressWidget = () => {
  const { t, i18n } = useTranslation(["home", "stats"]);
  const { data: stats, isLoading, isError, refetch } = useUserStats();
  const locale = i18n.resolvedLanguage ?? i18n.language;
  const count = numberFormat(locale);
  const percent = numberFormat(locale, { style: "percent", maximumFractionDigits: 0 });

  return (
    <HomeWidgetCard icon={Trophy} title={t("widgets.progress.title")} to="/user-stats">
      {isLoading ? (
        <div className="grid grid-cols-fill-36/4 gap-2">
          {Array.from({ length: 4 }).map((_, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list of skeletons has no id to key from
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))}
        </div>
      ) : isError || !stats ? (
        <StatusMessage onRetry={refetch} />
      ) : stats.tasks_completed_total === 0 ? (
        // Four zeros say nothing to somebody who has only just arrived.
        <HomeWidgetNotice icon={Flame}>{t("widgets.progress.firstTask")}</HomeWidgetNotice>
      ) : (
        <div className="grid grid-cols-fill-36/4 gap-2">
          <Stat icon={Flame} label={t("stats:metrics.currentStreak")}>
            {t("widgets.progress.streak", { count: stats.streak })}
          </Stat>
          <Stat icon={CheckCheck} label={t("stats:tasksCompleted.thisWeek")}>
            {count.format(stats.tasks_completed_this_week)}
          </Stat>
          <Stat icon={Target} label={t("stats:metrics.onTimeRate")}>
            {percent.format(stats.on_time_rate / 100)}
          </Stat>
          <Stat icon={Trophy} label={t("stats:tasksCompleted.allTime")}>
            {count.format(stats.tasks_completed_total)}
          </Stat>
        </div>
      )}
    </HomeWidgetCard>
  );
};
