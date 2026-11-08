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
import type { GridToggleOptions } from "@/hooks/useGridSelection";
import { LAYOUT_NAMESPACES } from "@/hooks/useLayoutEnv";
import { useCommunityPath } from "@/lib/communityUrl";
import { cardLines, FILE_COLUMN_OF, FILE_LIST_SHAPE } from "@/lib/layouts/files";
import type { ToolIndexRow } from "@/pages/community/tools/ToolIndexPage";
import type { TranslateFn } from "@/types/i18n";
import { fieldColumn } from "@/ui/layouts/columns";
import { cardOf, columnsOf, indexPaths } from "@/ui/layouts/draft";
import type { FieldDef, LayoutEnv } from "@/ui/layouts/fields";
import { type LayoutContext, type LayoutNode, LayoutTree, namesField } from "@/ui/layouts/tree";
import type { AppColumnDef } from "@/ui/lib/table";

import { CollectionGridView } from "./CollectionGridView";
import { CollectionMasonryView } from "./CollectionMasonryView";
import { CollectionTimelineView } from "./CollectionTimelineView";

/** A card under each file's picture, and how tall it stands for a file: what
 *  the masonry wall, which places files without measuring them, reserves. */
export type CollectionCard = {
  render: (file: CollectionFileSummary) => ReactNode;
  height: (file: CollectionFileSummary) => number;
  /** It shows each file's name, which its picture then need not on hover. */
  names: boolean;
};

/** One line of a card (as tall as a badge, its tallest part), the space
 *  between two, and above the first. */
const LINE = 22;
const SPACE = 4;
const ABOVE = 6;

const NO_HREF = () => "";

/** What a collection's fields are drawn with: the files namespace beside the
 *  layouts', and the community's paths. A file is opened from its picture or
 *  its name's own link, not through a title's. */
const useCollectionEnv = (
  stepCounter?: LayoutEnv<CollectionFileSummary>["stepCounter"]
): LayoutEnv<CollectionFileSummary> => {
  const { t } = useTranslation(["files", ...LAYOUT_NAMESPACES]);
  const communityPath = useCommunityPath();
  return useMemo(
    () => ({ t: t as TranslateFn, communityPath, itemHref: NO_HREF, stepCounter }),
    [t, communityPath, stepCounter]
  );
};

/**
 * The card a wall draws under each picture, or none where it shows no fields,
 * as a collection shipped draws its pictures alone. While the layout is
 * edited, each of its parts is marked for the editor to find.
 */
export const useCollectionCard = (
  card: LayoutNode,
  fields: ReadonlyMap<string, FieldDef<CollectionFileSummary>>,
  editing = false,
  stepCounter?: LayoutEnv<CollectionFileSummary>["stepCounter"]
): CollectionCard | undefined => {
  const env = useCollectionEnv(stepCounter);
  return useMemo(() => {
    if (!card.children?.length) return undefined;
    const view: LayoutContext<CollectionFileSummary> = {
      fields,
      card,
      variant: "card",
      env,
      editing: editing ? indexPaths(card) : undefined,
      oneLine: true,
    };
    const linesOf = (file: CollectionFileSummary) => cardLines(card, file, fields);
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
            <LayoutTree node={card} item={file} view={view} />
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
  fields: ReadonlyMap<string, FieldDef<CollectionFileSummary>>,
  editing = false,
  stepCounter?: LayoutEnv<CollectionFileSummary>["stepCounter"]
): AppColumnDef<ToolIndexRow>[] => {
  const env = useCollectionEnv(stepCounter);
  return useMemo(
    () =>
      ids.flatMap((id) => {
        const field = fields.get(id);
        if (!field) return [];
        const sorts = id === "name" || id in FILE_COLUMN_OF;
        const column = fieldColumn(field, env, {
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
  stepCounter,
}: {
  kind: CollectionList;
  definition: ListLayoutDefinitionInput;
  /** Every field the list can show, its ratings drawn as it says. */
  fields: ReadonlyMap<string, FieldDef<CollectionFileSummary>>;
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
  /** How its counters are stepped, where its reader may change them. */
  stepCounter?: LayoutEnv<CollectionFileSummary>["stepCounter"];
}) => {
  const card = useCollectionCard(
    cardOf(definition, fields, FILE_LIST_SHAPE),
    fields,
    editing,
    stepCounter
  );
  // The shipped columns are a fresh list each time: kept, so the table's
  // columns are made again only when what they show changes.
  const ids = useMemo(
    () => columnsOf({ columns: definition.columns }, fields, FILE_LIST_SHAPE),
    [definition.columns, fields]
  );
  const columns = useCollectionColumns(ids, fields, editing, stepCounter);
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
