/**
 * A target's layouts as read: the ways it lists what it holds and its details,
 * each drawn as shipped until it is changed; and the changes a save makes to
 * them, each on its own.
 */

import type {
  DetailLayoutDefinitionInput,
  DetailLayoutDefinitionOutput,
  DetailLayoutRead,
  ListLayoutRead,
  ListLayoutReadKind,
  ListLayoutWrite,
} from "@/api/generated/initiativeAPI.schemas";

/** One kind of item's detail, as read: the kind (an Initiative tool's, or a
 *  plug-in's own), for a detail laid out per type which type's, and its
 *  layout, which is stored once it is changed. */
export interface DetailLayout {
  kind: string;
  task_type_id?: number | null;
  task_type_name?: string | null;
  definition: DetailLayoutDefinitionOutput;
  updated_at: string | null;
}

/** A target's layouts, as read. */
export interface LayoutSet {
  layouts: (ListLayoutRead | DetailLayout)[];
}

/** Whether a layout is one of the ways its target lists what it holds, as
 *  against a detail. */
export const isListLayout = (layout: ListLayoutRead | DetailLayout): layout is ListLayoutRead =>
  "is_default" in layout;

/** The ways a target lists what it holds, in the order its tool draws them. */
export const listLayouts = (set: LayoutSet | undefined) =>
  (set?.layouts ?? []).filter(isListLayout);

/** One detail's layout as changed, or null where it is drawn as shipped. */
export const detailLayoutOf = (
  set: LayoutSet | undefined,
  kind: string,
  /** For a detail laid out per type (a project's task page), which type's. */
  taskTypeId?: number | null
): DetailLayoutDefinitionInput | null => {
  const layout = (set?.layouts ?? []).find(
    (each): each is DetailLayout =>
      !isListLayout(each) &&
      each.kind === kind &&
      (each.task_type_id ?? null) === (taskTypeId ?? null)
  );
  return layout?.updated_at ? (layout.definition as DetailLayoutDefinitionInput) : null;
};

/** One change to a target's layouts: one saved, one put back as shipped, or
 *  the list it opens on. A detail is changed by its kind (`K`): one of
 *  Initiative's tools' unless a plug-in's own are named. */
export type LayoutChange<K extends string = DetailLayoutRead["kind"]> =
  | {
      save:
        | ListLayoutWrite
        | { kind: K; task_type_id?: number | null; definition: DetailLayoutDefinitionInput };
    }
  | {
      reset: ListLayoutReadKind | K;
      /** For a detail laid out per type: which type's page. */
      taskTypeId?: number;
    }
  | { opensOn: ListLayoutReadKind };

/** Stores `changes`, in order, answering with the layouts as stored. A
 *  method, whose parameter TypeScript checks both ways: one that stores only
 *  Initiative's tools' details is taken where only theirs are laid out. */
export type SaveLayouts = {
  save(changes: LayoutChange<string>[]): Promise<LayoutSet | undefined>;
}["save"];
