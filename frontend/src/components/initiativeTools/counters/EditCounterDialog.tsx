import { MoreHorizontal, RotateCcw } from "lucide-react";
import { useRef } from "react";
import { useTranslation } from "react-i18next";

import { useReadCounter } from "@/api/generated/counters/counters";
import { type CounterRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { counterSaves, type SteppedCount, useResetCounter } from "@/hooks/useCounters";
import { usePendingShown } from "@/hooks/useFieldSave";
import { detailLayoutOf, instanceTarget, useToolLayouts } from "@/hooks/useToolLayouts";
import { COUNTER_DETAIL } from "@/lib/layouts/counterLayout";
import { DetailLayoutView } from "@/lib/layouts/DetailLayoutView";
import type { StoredRegions } from "@/lib/layouts/detailLayout";
import { usePluginMenuActions } from "@/lib/layouts/plugins";
import type { DialogProps } from "@/types/dialog";
import { Button } from "@/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";

type EditCounterDialogProps = DialogProps & {
  groupId: number;
  /** The group's initiative; a community's own group has none. */
  initiativeId: number | null;
  counter: CounterRead;
  /** The page's stepper, so a step taken here and one on the page are one. */
  stepper: SteppedCount;
  readOnly?: boolean;
};

/** A counter, drawn as its group lays it out, each field saved on its own. */
export const EditCounterDialog = ({
  open,
  onOpenChange,
  groupId,
  initiativeId,
  counter: listed,
  stepper,
  readOnly = false,
}: EditCounterDialogProps) => {
  const { t } = useTranslation(["counterGroups", "common"]);
  const communityId = useActiveCommunityId();
  // The group's counter is drawn until its own read, which also carries the
  // plug-ins' values, answers.
  const read = useReadCounter(communityId, listed.id, undefined, {
    query: { placeholderData: listed, enabled: open },
  });
  const counter = usePendingShown(counterSaves(groupId), listed.id, read.data) ?? listed;
  // A community's own group has no layouts of its own: it draws the shipped one.
  const layouts = useToolLayouts(
    open && initiativeId !== null ? instanceTarget(Tool.counter_group, groupId) : null
  );
  const pluginActions = usePluginMenuActions("counter", counter.id, initiativeId);
  const reset = useResetCounter(groupId);
  const leaving = useRef(false);

  const actions =
    !readOnly || pluginActions.items.length > 0 ? (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button type="button" variant="outline" size="icon" aria-label={t("more")}>
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {readOnly ? null : (
            <DropdownMenuItem
              onSelect={() => {
                stepper.cancel(counter.id);
                reset.mutate(counter.id);
              }}
            >
              <RotateCcw className="h-4 w-4" />
              {t("common:reset")}
            </DropdownMenuItem>
          )}
          {!readOnly && pluginActions.items.length > 0 ? <DropdownMenuSeparator /> : null}
          {pluginActions.items}
        </DropdownMenuContent>
      </DropdownMenu>
    ) : null;

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-3xl">
          <DialogTitle className="sr-only">{t("editCounter")}</DialogTitle>
          <DialogDescription className="sr-only">{counter.name}</DialogDescription>
          <DetailLayoutView
            detail={COUNTER_DETAIL}
            item={counter}
            layout={detailLayoutOf(layouts.data, "counter") as StoredRegions | null}
            context={{ readOnly, groupId, initiativeId, leaving, actions, stepper }}
          />
        </DialogContent>
      </Dialog>
      {pluginActions.dialog}
    </>
  );
};
