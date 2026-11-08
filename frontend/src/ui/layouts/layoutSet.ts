/**
 * A target's layouts as read: the ways it lists what it holds and its details,
 * each drawn as shipped until it is changed; and the changes a save makes to
 * them, each on its own.
 */

import type {
  DetailLayoutDefinitionInput,
  DetailLayoutRead,
  DetailLayoutWrite,
  ListLayoutRead,
  ListLayoutReadKind,
  ListLayoutWrite,
  ToolLayoutSetRead,
} from "@/api/generated/initiativeAPI.schemas";

/** Whether a layout is one of the ways its target lists what it holds, as
 *  against a detail. */
export const isListLayout = (layout: ListLayoutRead | DetailLayoutRead): layout is ListLayoutRead =>
  "is_default" in layout;

/** The ways a target lists what it holds, in the order its tool draws them. */
export const listLayouts = (set: Pick<ToolLayoutSetRead, "layouts"> | undefined) =>
  (set?.layouts ?? []).filter(isListLayout);

/** One detail's layout as changed, or null where it is drawn as shipped. */
export const detailLayoutOf = (
  set: ToolLayoutSetRead | undefined,
  kind: DetailLayoutRead["kind"],
  /** For a detail laid out per type (a project's task page), which type's. */
  taskTypeId?: number | null
): DetailLayoutDefinitionInput | null => {
  const layout = (set?.layouts ?? []).find(
    (each): each is DetailLayoutRead =>
      !isListLayout(each) &&
      each.kind === kind &&
      (each.task_type_id ?? null) === (taskTypeId ?? null)
  );
  return layout?.updated_at ? (layout.definition as DetailLayoutDefinitionInput) : null;
};

/** One change to a target's layouts: one saved, one put back as shipped, or
 *  the list it opens on. */
export type LayoutChange =
  | { save: ListLayoutWrite | DetailLayoutWrite }
  | {
      reset: ListLayoutReadKind | DetailLayoutRead["kind"];
      /** For a detail laid out per type: which type's page. */
      taskTypeId?: number;
    }
  | { opensOn: ListLayoutReadKind };
