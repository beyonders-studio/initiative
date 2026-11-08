/**
 * What Initiative hands a layout's views: the words they read, the community's
 * paths, the item links and the counters a list may step.
 */

import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { PropertyDefinitionRead, PropertyTarget } from "@/api/generated/initiativeAPI.schemas";
import { useStepCounter } from "@/hooks/useProperties";
import { useCommunityPath } from "@/lib/communityUrl";
import type { TranslateFn } from "@/types/i18n";
import type { LayoutEnv } from "@/ui/layouts/fields";

// The namespaces Initiative's layouts name their fields and parts in, loaded
// together so none shows as a key: an event's fields are named in
// `calendars`, whether or not an event is drawn beside them. `projects` is
// the one a key without a prefix is read in.
export const LAYOUT_NAMESPACES = [
  "projects",
  "layouts",
  "tasks",
  "dates",
  "relations",
  "calendars",
] as const;

/** How a list of `target`s steps its counters: an item's, where `may` says
 *  its reader may change that counter on it from the list. `may` is kept
 *  between renders by its caller. */
export const useCounterSteps = <I extends { id: number }>(
  target: PropertyTarget,
  may: (item: I, definition: PropertyDefinitionRead) => boolean
): NonNullable<LayoutEnv<I>["stepCounter"]> => {
  const { mutateAsync } = useStepCounter(target);
  return useCallback(
    (item, definition) =>
      may(item, definition) ? (up) => mutateAsync({ itemId: item.id, definition, up }) : null,
    [may, mutateAsync]
  );
};

/** The env of a project's views: one community, and its tasks' pages. */
export const useProjectLayoutEnv = (
  taskHref: (taskId: number) => string
): LayoutEnv<{ id: number }> => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const communityPath = useCommunityPath();
  return useMemo(
    () => ({ t: t as TranslateFn, communityPath, itemHref: (task) => taskHref(task.id) }),
    [t, communityPath, taskHref]
  );
};
