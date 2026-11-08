/**
 * What Initiative hands a layout's views: the words they read, the community's
 * paths, the item links and the counters a list may step.
 */

import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { PropertyDefinitionRead, PropertyTarget } from "@/api/generated/initiativeAPI.schemas";
import { useStepCounter } from "@/hooks/useProperties";
import { useCommunityPath } from "@/lib/communityUrl";
import { LAYOUT_NAMESPACES, type LayoutEnv, type LayoutItem } from "@/lib/layouts/fields";
import type { TranslateFn } from "@/types/i18n";

/** How a list of `target`s steps its counters: an item's, where `may` says
 *  its reader may change that counter on it from the list. `may` is kept
 *  between renders by its caller. */
export const useCounterSteps = (
  target: PropertyTarget,
  may: (item: LayoutItem, definition: PropertyDefinitionRead) => boolean
): NonNullable<LayoutEnv["stepCounter"]> => {
  const { mutateAsync } = useStepCounter(target);
  return useCallback(
    (item, definition) =>
      may(item, definition) ? (up) => mutateAsync({ itemId: item.id, definition, up }) : null,
    [may, mutateAsync]
  );
};

/** The env of a project's views: one community, and its tasks' pages. */
export const useProjectLayoutEnv = (taskHref: (taskId: number) => string): LayoutEnv => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const communityPath = useCommunityPath();
  return useMemo(
    () => ({ t: t as TranslateFn, communityPath, itemHref: (task) => taskHref(task.id) }),
    [t, communityPath, taskHref]
  );
};
