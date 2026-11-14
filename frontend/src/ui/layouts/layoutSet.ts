/**
 * A target's layouts as read: the ways it lists what it holds and its details,
 * each drawn as shipped until it is changed; and the changes a save makes to
 * them, each on its own.
 */

import type {
  DetailLayoutDefinitionInput,
  DetailLayoutDefinitionOutput,
  DetailLayoutRead,
  LayoutPreset,
  ListLayoutDefinitionInput,
  ListLayoutRead,
  ListLayoutReadKind,
  SortField,
} from "@/api/generated/initiativeAPI.schemas";

/** A preset as a list's layout keeps it: its name (none for a shipped one no
 *  one renamed), its slug, and its tool's filters and sort, by the tool's own
 *  fields. */
export interface StoredPreset {
  name?: string | null;
  slug: string;
  filters?: object;
  sort?: SortField[];
}

/** How a list draws what it lists, as kept, its presets (`P`) its tool's own. */
export type ListLayoutDefinition<P extends StoredPreset = StoredPreset> = Omit<
  ListLayoutDefinitionInput,
  "presets"
> & { presets?: P[] | null };

/** One of the ways a target lists what it holds, as read. */
export type ListView = Omit<ListLayoutRead, "definition"> & { definition: ListLayoutDefinition };

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
  layouts: (ListView | DetailLayout)[];
}

/** Whether a layout is one of the ways its target lists what it holds, as
 *  against a detail. */
export const isListLayout = (layout: ListView | DetailLayout): layout is ListView =>
  "is_default" in layout;

/** The ways a target lists what it holds, in the order its tool draws them,
 *  as the app's own set types them. */
export const listLayouts = <S extends LayoutSet>(
  set: S | undefined
): Extract<S["layouts"][number], ListView>[] =>
  (set?.layouts ?? []).filter((each): each is Extract<S["layouts"][number], ListView> =>
    isListLayout(each)
  );

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
 *  the list it opens on. A detail is changed by its kind (`K`), and a list
 *  saved with its presets (`P`): Initiative's tools' unless a plug-in's own
 *  are named. */
export type LayoutChange<
  K extends string = DetailLayoutRead["kind"],
  P extends StoredPreset = LayoutPreset,
> =
  | {
      save:
        | { kind: ListLayoutReadKind; definition: ListLayoutDefinition<P> }
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
 *  Initiative's tools' layouts is taken where only theirs are laid out. */
export type SaveLayouts = {
  save(changes: LayoutChange<string, StoredPreset>[]): Promise<LayoutSet | undefined>;
}["save"];
