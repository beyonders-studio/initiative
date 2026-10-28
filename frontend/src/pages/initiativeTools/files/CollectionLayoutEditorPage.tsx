/**
 * `/files/collections/$collectionId/layouts` — a collection's layouts (its
 * walls and table, and the page a file opens on from it), edited in place:
 * each wall's card and the table's columns, and the file's page, chosen from
 * a file's own fields, the collection's properties and the initiative's
 * metadata, drawn with the collection's own files. The collection's
 * properties are managed here too, beside the layouts they show on.
 * `?layout=file` opens on the file's page.
 *
 * Who may is the server's answer on the set. The editor itself says when the
 * screen is too narrow to edit on, and keeps its draft while it is.
 */

import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { useMemo } from "react";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  type CollectionList,
  CollectionListView,
} from "@/components/files/collections/collectionLists";
import { fileDetail } from "@/components/layouts/details";
import { type EditableLists, LayoutEditor } from "@/components/layouts/LayoutEditor";
import { ToolSettingsPermissionRequired } from "@/components/tools/settings/ToolSettingsGuard";
import type { ToolIndexRow } from "@/components/tools/ToolIndexPage";
import { ToolIndexTable } from "@/components/tools/ToolIndexTable";
import { useCollection, useCollectionFilesFeed } from "@/hooks/useCollections";
import { useProperties } from "@/hooks/useProperties";
import { instanceTarget, useInstanceLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import { collectionFileFields, FILE_LIST_SHAPE } from "@/lib/layouts/files";
import { collectionRoute } from "@/lib/tools";

const noop = () => {};
const NO_SELECTION = {
  active: false,
  selectedIds: new Set<number>(),
  toggle: noop,
  setMany: noop,
};

/** The files the preview draws: the collection's first page, newest added
 *  first, as the collection opens on. */
const NEWEST_ADDED = { sort_by: "added_at", sort_dir: "desc" };

export const CollectionLayoutEditorPage = () => {
  const { collectionId } = useParams({ strict: false }) as { collectionId?: string };
  const { layout } = useSearch({ strict: false }) as { layout?: string };
  const parsedId = collectionId ? Number(collectionId) : Number.NaN;
  const id = Number.isFinite(parsedId) ? parsedId : null;
  const navigate = useNavigate();
  const gp = useCommunityPath();

  const collection = useCollection(id).data;
  const set = useInstanceLayouts("collection", id).data;
  const feed = useCollectionFilesFeed(id, NEWEST_ADDED);
  const files = useMemo(() => feed.data?.pages[0]?.items ?? [], [feed.data]);
  const { data: properties = [] } = useProperties({
    initiativeId: collection?.initiative_id,
    enabled: collection !== undefined,
  });
  const rows = useMemo(
    () => files.map((file) => ({ ...file, card: null }) as ToolIndexRow),
    [files]
  );
  const lists = useMemo<EditableLists | null>(
    () =>
      collection
        ? {
            fields: collectionFileFields(collection.metadata, properties),
            shape: FILE_LIST_SHAPE,
            owner: { kind: "collection", id: collection.id },
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
          }
        : null,
    [collection, properties, files, rows]
  );
  const details = useMemo(
    () => (collection ? [fileDetail(collection, files[0], feed.isSuccess)] : []),
    [collection, files, feed.isSuccess]
  );

  if (!collection || !set || !lists) return null;
  if (!set.can_configure) return <ToolSettingsPermissionRequired />;
  return (
    <LayoutEditor
      // Another collection's editor starts afresh: a draft, and the question
      // before leaving it, belong to the collection they were made for.
      key={collection.id}
      target={instanceTarget("collection", collection.id)}
      initiativeId={collection.initiative_id}
      lists={lists}
      details={details}
      set={set}
      initialKind={layout}
      onClose={() =>
        void navigate({ to: gp(collectionRoute(collection.initiative_id, collection.id)) })
      }
    />
  );
};
