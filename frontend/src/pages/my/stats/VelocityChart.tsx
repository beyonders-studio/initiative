import { format, parseISO } from "date-fns";
import { useTranslation } from "react-i18next";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { VelocityWeekData } from "@/api/generated/initiativeAPI.schemas";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { ChartContainer, ChartTooltipContent } from "@/ui/chart";

interface VelocityChartProps {
  data: VelocityWeekData[];
}

export function VelocityChart({ data }: VelocityChartProps) {
  const { t } = useTranslation("stats");

  const chartConfig = {
    assigned: {
      label: t("velocity.assigned"),
      color: "var(--chart-1)",
    },
    completed: {
      label: t("velocity.completed"),
      color: "var(--chart-2)",
    },
  };
  // Format data for display
  const formattedData = data.map((week) => ({
    ...week,
    weekLabel: format(parseISO(week.week_start), "MMM d"),
  }));

  if (data.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("velocity.title")}</CardTitle>
          <CardDescription>{t("velocity.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex h-[300px] items-center justify-center text-muted-foreground text-sm">
            {t("velocity.noData")}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("velocity.title")}</CardTitle>
        <CardDescription>{t("velocity.descriptionLong")}</CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={chartConfig} className="h-[300px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={formattedData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="weekLabel"
                tick={{ fontSize: 12 }}
                tickLine={false}
                axisLine={false}
              />
              <YAxis tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
              <Tooltip content={<ChartTooltipContent />} />
              <Legend />
              <Bar dataKey="assigned" fill="var(--color-assigned)" radius={[4, 4, 0, 0]} />
              <Bar dataKey="completed" fill="var(--color-completed)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
