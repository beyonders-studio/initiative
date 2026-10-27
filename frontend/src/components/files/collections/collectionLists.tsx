/**
 * What a collection's lists draw of each file, as its layouts say: a card of
 * fields under each picture on its walls, and its table's columns.
 */

import { type ReactNode, useMemo } from "react";
import { useTranslation } from "react-i18next";

import type {
  CollectionFileSummary,
  FileSummary,
  ListLayoutDefinitionInput,
  ListLayoutReadKind,
  TimelineBucket,
} from "@/api/generated/initiativeAPI.schemas";
import { CollectionGridView } from "@/components/files/collections/CollectionGridView";
import { CollectionMasonryView } from "@/components/files/collections/CollectionMasonryView";
import { CollectionTimelineView } from "@/components/files/collections/CollectionTimelineView";
import type { ToolIndexRow } from "@/components/tools/ToolIndexPage";
import type { GridToggleOptions } from "@/hooks/useGridSelection";
import { useCommunityPath } from "@/lib/communityUrl";
import { fieldColumn } from "@/lib/layouts/columns";
import { cardOf, columnsOf, indexPaths } from "@/lib/layouts/draft";
import {
  type FieldDef,
  LAYOUT_NAMESPACES,
  type LayoutEnv,
  type LayoutItem,
} from "@/lib/layouts/fields";
import { cardLines, FILE_COLUMN_OF, FILE_LIST_SHAPE } from "@/lib/layouts/files";
import { type LayoutContext, type LayoutNode, LayoutTree, namesField } from "@/lib/layouts/tree";
import type { AppColumnDef } from "@/lib/table";
import type { TranslateFn } from "@/types/i18n";

/** A card under each file's picture, and how tall it stands for a file: what
 *  the masonry wall, which places files without measuring them, reserves. */
export type CollectionCard = {
  render: (file: CollectionFileSummary) => ReactNode;
  height: (file: CollectionFileSummary) => number;
  /** It shows each file's name, which its picture then need not on hover. */
  names: boolean;
};

/** One line of a card, the space between two, and above the first. */
const LINE = 20;
const SPACE = 4;
const ABOVE = 6;

const NO_TASK_HREF = () => "";

/** What a collection's fields are drawn with: the files namespace beside the
 *  layouts', and the community's paths. A file is opened from its picture or
 *  its name's own link, not through a task's. */
const useCollectionEnv = (): LayoutEnv => {
  const { t } = useTranslation(["files", ...LAYOUT_NAMESPACES]);
  const communityPath = useCommunityPath();
  return useMemo(
    () => ({ t: t as TranslateFn, communityPath, taskHref: NO_TASK_HREF }),
    [t, communityPath]
  );
};

/**
 * The card a wall draws under each picture, or none where it shows no fields,
 * as a collection shipped draws its pictures alone. While the layout is
 * edited, each of its parts is marked for the editor to find.
 */
export const useCollectionCard = (
  card: LayoutNode,
  fields: ReadonlyMap<string, FieldDef>,
  editing = false
): CollectionCard | undefined => {
  const env = useCollectionEnv();
  return useMemo(() => {
    if (!card.children?.length) return undefined;
    const view: LayoutContext = {
      fields,
      card,
      variant: "card",
      env,
      editing: editing ? indexPaths(card) : undefined,
    };
    const linesOf = (file: CollectionFileSummary) =>
      cardLines(card, file as unknown as LayoutItem, fields);
    const height = (file: CollectionFileSummary) => {
      const lines = linesOf(file);
      return lines === 0 ? 0 : ABOVE + lines * LINE + (lines - 1) * SPACE;
    };
    return {
      height,
      names: namesField(card, "name"),
      render: (file) =>
        editing || linesOf(file) > 0 ? (
          <div
            className="space-y-1 overflow-hidden pt-1.5 text-xs leading-5"
            style={editing ? undefined : { height: height(file) }}
          >
            <LayoutTree node={card} item={file as unknown as LayoutItem} view={view} />
          </div>
        ) : null,
    };
  }, [card, fields, env, editing]);
};

/**
 * A collection's table as its layout lays it out: a column for each field it
 * names, in order. The file's own dates sort by what the server sorts them
 * by; the rest do not sort. While the layout is edited, each column's header
 * is marked for the editor to find.
 */
export const useCollectionColumns = (
  ids: readonly string[],
  fields: ReadonlyMap<string, FieldDef>,
  editing = false
): AppColumnDef<ToolIndexRow>[] => {
  const env = useCollectionEnv();
  return useMemo(
    () =>
      ids.flatMap((id) => {
        const field = fields.get(id);
        if (!field) return [];
        const sorts = id === "name" || id in FILE_COLUMN_OF;
        const column = fieldColumn<LayoutItem>(field, env, {
          id: FILE_COLUMN_OF[id] ?? id,
          ...(sorts ? { sortFn: "alphanumeric" as const } : {}),
        });
        const { header } = column;
        return [
          (editing && typeof header === "function"
            ? {
                ...column,
                header: (context: Parameters<typeof header>[0]) => (
                  <span className="contents" data-layout-node={`column:${id}`}>
                    {header(context)}
                  </span>
                ),
              }
            : column) as unknown as AppColumnDef<ToolIndexRow>,
        ];
      }),
    [ids, fields, env, editing]
  );
};

/** The lists a collection may lay its files out as. */
export type CollectionList = Extract<ListLayoutReadKind, "masonry" | "grid" | "timeline" | "table">;

/**
 * A collection's files drawn as one of its lists, as its layout says: the
 * walls with each file's card under its picture, or the table, which the
 * caller draws with the layout's columns. With `editing`, as the layout
 * editor draws it, each part marked.
 */
export const CollectionListView = ({
  kind,
  definition,
  fields,
  files,
  groupByTags = false,
  buckets = NO_BUCKETS,
  onJump = noop,
  onActivate,
  selecting,
  isSelected,
  table,
  editing = false,
}: {
  kind: CollectionList;
  definition: ListLayoutDefinitionInput;
  /** Every field the list can show, its ratings drawn as it says. */
  fields: ReadonlyMap<string, FieldDef>;
  files: CollectionFileSummary[];
  groupByTags?: boolean;
  /** The months files were added in, which the timeline's rail is drawn from. */
  buckets?: TimelineBucket[];
  onJump?: (bucket: TimelineBucket) => void;
  onActivate: (file: FileSummary, options: GridToggleOptions) => void;
  selecting?: boolean;
  isSelected?: (file: FileSummary) => boolean;
  table: (columns: AppColumnDef<ToolIndexRow>[]) => ReactNode;
  editing?: boolean;
}) => {
  const card = useCollectionCard(cardOf(definition, fields, FILE_LIST_SHAPE), fields, editing);
  const columns = useCollectionColumns(
    columnsOf(definition, fields, FILE_LIST_SHAPE),
    fields,
    editing
  );
  const walls = { files, card, onActivate, selecting, isSelected };
  if (kind === "table") return table(columns);
  if (kind === "timeline") {
    return <CollectionTimelineView {...walls} buckets={buckets} onJump={onJump} />;
  }
  return kind === "masonry" ? (
    <CollectionMasonryView {...walls} groupByTags={groupByTags} />
  ) : (
    <CollectionGridView {...walls} groupByTags={groupByTags} />
  );
};

const NO_BUCKETS: TimelineBucket[] = [];
const noop = () => {};
