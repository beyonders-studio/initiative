import { Ban } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  SearchEntityType,
  type TaskListRead,
  type TaskRead,
} from "@/api/generated/initiativeAPI.schemas";
import { EntityCard } from "@/components/entities/EntityCard";
import { useRelationshipsFor } from "@/hooks/useRelationships";
import { groupOf, RELATION_GROUPS } from "@/lib/relationships";
import { Button } from "@/ui/button";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/ui/hover-card";
import { cn } from "@/ui/lib/utils";

interface TaskBlockersHoverCardProps {
  task: Pick<TaskListRead | TaskRead, "id" | "blocked_by_open_count">;
  className?: string;
}

/**
 * What is holding a task up, where the task is read.
 *
 * A project used to carry a **Blocked** column, and retiring it moved that fact
 * onto the task — where, until this, it only existed inside a panel somebody
 * had to open. A count on the row puts the signal back; hovering says what the
 * things actually are, because a number tells you to look and only the names
 * tell you why.
 *
 * Sits beside the description mark and behaves the same: nothing is drawn when
 * there is nothing to say, and the list is fetched only once somebody asks for
 * it, so a table of two hundred rows costs two hundred integers and no
 * requests.
 */
export const TaskBlockersHoverCard = ({ task, className }: TaskBlockersHoverCardProps) => {
  const { t } = useTranslation("relations");
  const [open, setOpen] = useState(false);
  const count = task.blocked_by_open_count ?? 0;

  const { data: rows = [] } = useRelationshipsFor(
    { type: SearchEntityType.task, id: task.id },
    { enabled: open }
  );
  const blockers = rows.filter(
    (row) => groupOf(row, [RELATION_GROUPS.blockedBy]) !== null && row.other.is_open !== false
  );

  if (count === 0) return null;

  return (
    <HoverCard open={open} onOpenChange={setOpen}>
      <HoverCardTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={t("blockers.icon")}>
          <Ban className={cn("h-4 w-4 text-warning", className)} />
        </Button>
      </HoverCardTrigger>
      <HoverCardContent className="w-72" align="start">
        <p className="font-medium text-sm">{t("blockers.label", { count })}</p>
        <ul className="mt-2 flex flex-col gap-1.5">
          {blockers.map((edge) => (
            <li key={edge.id}>
              <EntityCard variant="compact" end={edge.other} isOpen={edge.other.is_open} />
            </li>
          ))}
        </ul>
      </HoverCardContent>
    </HoverCard>
  );
};
