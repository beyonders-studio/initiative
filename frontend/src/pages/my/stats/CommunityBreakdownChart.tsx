import { useTranslation } from "react-i18next";
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import type { CommunityTaskBreakdown } from "@/api/generated/initiativeAPI.schemas";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { ChartContainer, ChartTooltipContent } from "@/ui/chart";

interface CommunityBreakdownChartProps {
  data: CommunityTaskBreakdown[];
}

const COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

export function CommunityBreakdownChart({ data }: CommunityBreakdownChartProps) {
  const { t } = useTranslation("stats");
  if (data.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("communityBreakdown.title")}</CardTitle>
          <CardDescription>{t("communityBreakdown.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex h-[300px] items-center justify-center text-muted-foreground text-sm">
            {t("communityBreakdown.noData")}
          </div>
        </CardContent>
      </Card>
    );
  }

  const chartConfig = data.reduce(
    (acc, community, index) => {
      acc[`community_${community.community_id}`] = {
        label: community.community_name,
        color: COLORS[index % COLORS.length],
      };
      return acc;
    },
    {} as Record<string, { label: string; color: string }>
  );

  // Format data for pie chart
  const pieData = data.map((community) => ({
    name: community.community_name,
    value: community.completed_count,
    community_id: community.community_id,
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("communityBreakdown.title")}</CardTitle>
        <CardDescription>{t("communityBreakdown.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={chartConfig} className="h-[300px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={pieData}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) => `${name}: ${((percent ?? 0) * 100).toFixed(0)}%`}
                outerRadius={80}
                fill="#8884d8"
                dataKey="value"
              >
                {pieData.map((entry, index) => (
                  <Cell key={`cell-${entry.community_id}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip content={<ChartTooltipContent />} />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
