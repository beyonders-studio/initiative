import { parseISO } from "date-fns";
import { useTranslation } from "react-i18next";

import type { HeatmapDayData } from "@/api/generated/initiativeAPI.schemas";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { dateTimeFormat } from "@/ui/lib/intl";
import { cn } from "@/ui/lib/utils";

interface HeatmapChartProps {
  data: HeatmapDayData[];
}

export function HeatmapChart({ data }: HeatmapChartProps) {
  const { t } = useTranslation("stats");
  if (data.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("heatmap.title")}</CardTitle>
          <CardDescription>{t("heatmap.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex h-[200px] items-center justify-center text-muted-foreground text-sm">
            {t("heatmap.noData")}
          </div>
        </CardContent>
      </Card>
    );
  }

  // Find max activity for scaling
  const maxActivity = Math.max(...data.map((d) => d.activity_count), 1);

  // Get intensity level based on activity count
  const getIntensity = (count: number): string => {
    if (count === 0) return "bg-muted";
    const ratio = count / maxActivity;
    if (ratio < 0.25) return "bg-green-200 dark:bg-green-900/40";
    if (ratio < 0.5) return "bg-green-400 dark:bg-green-700/60";
    if (ratio < 0.75) return "bg-green-600 dark:bg-green-500/80";
    return "bg-green-700 dark:bg-green-400";
  };

  // Group data by weeks (7 days per week)
  const weeks: HeatmapDayData[][] = [];
  for (let i = 0; i < data.length; i += 7) {
    weeks.push(data.slice(i, i + 7));
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("heatmap.title")}</CardTitle>
        <CardDescription>{t("heatmap.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <div className="inline-flex gap-1">
            {weeks.map((week) => (
              <div key={`week-${week[0]?.date}`} className="flex flex-col gap-1">
                {week.map((day) => {
                  const date = parseISO(day.date);
                  const dateStr = dateTimeFormat("en-US", {
                    month: "short",
                    day: "numeric",
                  }).format(date);

                  return (
                    <div
                      key={day.date}
                      className={cn(
                        "h-3 w-3 rounded-sm transition-colors hover:ring-2 hover:ring-primary",
                        getIntensity(day.activity_count)
                      )}
                      title={`${dateStr}: ${t("heatmap.activity", { count: day.activity_count })}`}
                    />
                  );
                })}
              </div>
            ))}
          </div>
        </div>
        <div className="mt-4 flex items-center gap-2 text-muted-foreground text-xs">
          <span>{t("heatmap.less")}</span>
          <div className="h-3 w-3 rounded-sm bg-muted" />
          <div className="h-3 w-3 rounded-sm bg-green-200 dark:bg-green-900/40" />
          <div className="h-3 w-3 rounded-sm bg-green-400 dark:bg-green-700/60" />
          <div className="h-3 w-3 rounded-sm bg-green-600 dark:bg-green-500/80" />
          <div className="h-3 w-3 rounded-sm bg-green-700 dark:bg-green-400" />
          <span>{t("heatmap.more")}</span>
        </div>
      </CardContent>
    </Card>
  );
}
