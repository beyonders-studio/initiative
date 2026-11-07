import { useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { SmartChipKind, SmartChipTone } from "@/api/generated/initiativeAPI.schemas";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useChipState } from "@/hooks/useSmartChips";
import { useSetTaskDone } from "@/hooks/useTasks";
import { communityPath } from "@/lib/communityUrl";
import { chipRef } from "@/lib/smartChips";
import { entityRefRoute } from "@/lib/tools";
import { Checkbox } from "@/ui/checkbox";
import { cn } from "@/ui/lib/utils";

interface ChecklistChipProps {
  entityId: number;
  /** The title stored in the document, shown when the task cannot be read. */
  fallback: string;
}

/**
 * A task as a line to tick: its box, then its name.
 *
 * Ticking it finishes the task itself, so a list of these in a document is a
 * list of real work rather than a copy of it. The box is offered only where
 * the server says this reader may change the task; the name opens it.
 */
export function ChecklistChip({ entityId, fallback }: ChecklistChipProps) {
  const { t } = useTranslation(["editor", "tasks"]);
  const navigate = useNavigate();
  const communityId = useActiveCommunityId();
  const state = useChipState(chipRef(SmartChipKind["task:checklist"], entityId));
  const { setDone, pending } = useSetTaskDone();

  const live = state !== undefined;
  const done = state?.tone === SmartChipTone.good;

  return (
    <span className="mx-[0.15em] inline-flex items-baseline gap-[0.4em] align-baseline">
      <Checkbox
        checked={done}
        disabled={!state?.writable || pending}
        onCheckedChange={(value) => void setDone(entityId, value === true)}
        aria-label={done ? t("tasks:checkbox.markInProgress") : t("tasks:checkbox.markDone")}
        className="size-[1em] self-center"
      />
      <button
        type="button"
        onClick={() =>
          live &&
          void navigate({ to: communityPath(communityId, entityRefRoute("task", entityId)) })
        }
        aria-disabled={!live}
        title={live ? undefined : t("references.unavailable")}
        className={cn(
          "font-medium",
          live ? "cursor-pointer hover:underline" : "cursor-default text-muted-foreground/80",
          done && "text-muted-foreground"
        )}
      >
        {state?.title ?? fallback}
      </button>
    </span>
  );
}
