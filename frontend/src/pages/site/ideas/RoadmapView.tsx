/**
 * The Roadmap: the board's in-progress statuses, then Shipped, each a column
 * of the project board's own kind holding its suggestions, most voted first.
 * Nothing moves here. On a narrow page one column shows at a time, chosen by
 * its status, so nothing scrolls sideways.
 */

import { Link, Navigate } from "@tanstack/react-router";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { IdeaRoadmapColumn } from "@/api/generated/initiativeAPI.schemas";
import { VoteButton } from "@/components/ideas/IdeaParts";
import { useIdeaRoadmap } from "@/hooks/useIdeas";
import { BoardColumn, boardStackClass } from "@/ui/board-column";
import { Card } from "@/ui/card";
import { cn } from "@/ui/lib/utils";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

/** One status's column: a list under its heading. */
const RoadmapColumn = ({
  column,
  next,
  className,
}: {
  column: IdeaRoadmapColumn;
  next: string;
  className?: string;
}) => {
  const { t } = useTranslation("intake");
  const nameId = useId();
  return (
    <BoardColumn
      status={column.status}
      Name="h2"
      nameId={nameId}
      count={
        <span className="text-muted-foreground text-xs tabular-nums">
          {t("ideas.count", { count: column.items.length })}
        </span>
      }
      className={cn("h-auto max-h-[75vh] min-w-0 flex-1", className)}
    >
      <ul aria-labelledby={nameId} className={boardStackClass()}>
        {column.items.map((idea) => (
          <li key={idea.task_id}>
            <Card className="space-y-2 rounded-lg p-3">
              <Link
                to="/suggestions/$taskId"
                params={{ taskId: String(idea.task_id) }}
                className="block font-semibold leading-snug hover:underline"
              >
                {idea.title}
              </Link>
              <div className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate text-muted-foreground text-sm">
                  {idea.category}
                </span>
                <VoteButton idea={idea} next={next} size="lg" />
              </div>
            </Card>
          </li>
        ))}
      </ul>
    </BoardColumn>
  );
};

export const RoadmapView = ({ next }: { next: string }) => {
  const { t } = useTranslation("intake");
  const { data, isError } = useIdeaRoadmap();
  const columns = data?.columns ?? [];
  // The column a narrow page shows; the first until another is chosen.
  const [chosen, setChosen] = useState<number | null>(null);
  const shown = columns.some((column) => column.status.id === chosen)
    ? chosen
    : (columns[0]?.status.id ?? null);

  if (isError) return <Navigate to="/" replace />;

  return (
    <div className="space-y-3">
      {columns.length ? (
        <Select value={String(shown)} onValueChange={(value) => setChosen(Number(value))}>
          <SelectTrigger aria-label={t("ideas.statusLabel")} className="canvas-md:hidden h-11">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {columns.map((column) => (
              <SelectItem key={column.status.id} value={String(column.status.id)}>
                {column.status.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}
      <div className="flex gap-3">
        {columns.map((column) => (
          <RoadmapColumn
            key={column.status.id}
            column={column}
            next={next}
            className={column.status.id === shown ? undefined : "canvas-md:flex hidden"}
          />
        ))}
      </div>
    </div>
  );
};
