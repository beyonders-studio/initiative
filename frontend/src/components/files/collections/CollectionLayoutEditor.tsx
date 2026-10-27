import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  type CollectionFileSummary,
  type CollectionRead,
  Tool,
  type ToolLayoutSetRead,
} from "@/api/generated/initiativeAPI.schemas";
import {
  type CollectionList,
  CollectionListView,
} from "@/components/files/collections/collectionLists";
import { type EditableLists, LayoutEditor } from "@/components/layouts/LayoutEditor";
import type { ToolIndexRow } from "@/components/tools/ToolIndexPage";
import { ToolIndexTable } from "@/components/tools/ToolIndexTable";
import { useProperties } from "@/hooks/useProperties";
import { instanceTarget } from "@/hooks/useToolLayouts";
import { collectionFileFields, FILE_LIST_SHAPE } from "@/lib/layouts/files";

const noop = () => {};
const NO_SELECTION = {
  active: false,
  selectedIds: new Set<number>(),
  toggle: noop,
  setMany: noop,
};

/**
 * A collection's lists, edited where they are seen: each wall's card and the
 * table's columns, chosen from a file's own fields, the collection's fields
 * and the initiative's properties, drawn over the collection's own files.
 */
export const CollectionLayoutEditor = ({
  collection,
  set,
  files,
  onClose,
}: {
  collection: CollectionRead;
  /** Its layouts, read by someone who may change them. */
  set: ToolLayoutSetRead;
  /** The files the page has loaded, which the preview draws. */
  files: CollectionFileSummary[];
  onClose: () => void;
}) => {
  // The names of a file's own fields are in Files' words.
  useTranslation("files");
  const { data: properties = [] } = useProperties({ initiativeId: collection.initiative_id });
  const rows = useMemo(
    () => files.map((file) => ({ ...file, card: null }) as ToolIndexRow),
    [files]
  );
  const lists = useMemo<EditableLists>(
    () => ({
      fields: collectionFileFields(collection.fields, properties),
      shape: FILE_LIST_SHAPE,
      collectionId: collection.id,
      help: (kind) => `files:collections.listHelp.${kind}`,
      preview: (layout, fields) => (
        <CollectionListView
          kind={layout.kind as CollectionList}
          definition={layout.definition}
          fields={fields}
          files={files}
          onActivate={noop}
          editing
          table={(columns) => (
            <ToolIndexTable
              tool={Tool.file}
              initiativeId={collection.initiative_id}
              rows={rows}
              laidOut={columns}
              selection={NO_SELECTION}
              sorting={[]}
              onSortingChange={noop}
              columnVisibility={{}}
              onColumnVisibilityChange={noop}
            />
          )}
        />
      ),
    }),
    [collection, properties, files, rows]
  );
  return (
    <LayoutEditor
      target={instanceTarget("collection", collection.id)}
      initiativeId={collection.initiative_id}
      lists={lists}
      details={[]}
      set={set}
      onClose={onClose}
    />
  );
};
