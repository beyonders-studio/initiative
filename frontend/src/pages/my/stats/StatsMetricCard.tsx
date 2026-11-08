import type { LucideIcon } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { cn } from "@/ui/lib/utils";

interface StatsMetricCardProps {
  icon: LucideIcon;
  title: string;
  value: number | string | null;
  unit?: string;
  subtitle?: string;
  variant?: "default" | "success" | "warning" | "danger";
}

export function StatsMetricCard({
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
