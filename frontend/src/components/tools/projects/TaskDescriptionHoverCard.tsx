import { TextAlignStart } from "lucide-react";
import { useState } from "react";

import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { useReadTask } from "@/api/generated/tasks/tasks";
import { TaskDescription } from "@/components/tasks/TaskDescription";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { Button } from "@/ui/button";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/ui/hover-card";
import { cn } from "@/ui/lib/utils";

interface TaskDescriptionHoverCardProps {
  task: Pick<TaskListRead, "id" | "community_id" | "has_description" | "description_excerpt">;
  className?: string;
}

/**
 * A task's description, where the task is a row in a list.
 *
 * A list row carries only an excerpt, so the whole text is read from the task
 * once the card opens, under the key the task's own page reads it with; the
 * excerpt stands in while it loads. Either is read in the task's own
 * community, which on a cross-community list is not the page's.
 */
export const TaskDescriptionHoverCard = ({ task, className }: TaskDescriptionHoverCardProps) => {
  const [open, setOpen] = useState(false);
  const activeCommunityId = useActiveCommunityId();
  const { data } = useReadTask(task.community_id ?? activeCommunityId, task.id, undefined, {
    query: { enabled: open },
  });

  if (!task.has_description) return null;

  return (
    <HoverCard open={open} onOpenChange={setOpen}>
      <HoverCardTrigger asChild>
        <Button variant="ghost" size="icon-sm">
          <TextAlignStart className={cn("h-4 w-4", className)} />
        </Button>
      </HoverCardTrigger>
      <HoverCardContent className="max-h-120 w-screen max-w-120 overflow-y-auto">
        <TaskDescription
          content={data?.description || task.description_excerpt || ""}
          communityId={task.community_id ?? undefined}
        />
      </HoverCardContent>
    </HoverCard>
  );
};
