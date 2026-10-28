/**
 * `/files/collections/$collectionId/layouts` — a collection's layouts (its
 * walls and table, and a file opened from it), edited in place: each wall's
 * card and the table's columns, and the file's detail, chosen from a file's
 * own fields, the collection's metadata and the initiative's properties,
 * drawn with the collection's own files. The collection's metadata is
 * managed here too: renamed, reordered and deleted.
 *
 * Who may is the server's answer on the set. The editor itself says when the
 * screen is too narrow to edit on, and keeps its draft while it is.
 */

import { useNavigate, useParams } from "@tanstack/react-router";
import { Tags } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  type CollectionList,
  CollectionListView,
} from "@/components/files/collections/collectionLists";
import { InitiativeSettingsPropertiesTab } from "@/components/initiatives/settings/InitiativeSettingsPropertiesTab";
import { fileDetail } from "@/components/layouts/details";
import { type EditableLists, LayoutEditor } from "@/components/layouts/LayoutEditor";
import { ToolSettingsPermissionRequired } from "@/components/tools/settings/ToolSettingsGuard";
import type { ToolIndexRow } from "@/components/tools/ToolIndexPage";
import { ToolIndexTable } from "@/components/tools/ToolIndexTable";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
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
  // The names of a file's own fields are in Files' words.
  const { t } = useTranslation("files");
  const [managing, setManaging] = useState(false);
  const { collectionId } = useParams({ strict: false }) as { collectionId?: string };
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
      actions={
        <>
          <Button type="button" variant="outline" size="sm" onClick={() => setManaging(true)}>
            <Tags className="h-4 w-4" />
            {t("collections.properties.title")}
          </Button>
          <Dialog open={managing} onOpenChange={setManaging}>
            {/* The manager says what it holds. */}
            <DialogContent className="sm:max-w-3xl" aria-describedby={undefined}>
              <DialogHeader>
                <DialogTitle>{t("collections.properties.title")}</DialogTitle>
              </DialogHeader>
              <InitiativeSettingsPropertiesTab
                initiativeId={collection.initiative_id}
                owner={{ kind: "collection", id: collection.id }}
                canManage={collection.can.edit}
              />
            </DialogContent>
          </Dialog>
        </>
      }
      onClose={() =>
        void navigate({ to: gp(collectionRoute(collection.initiative_id, collection.id)) })
      }
    />
  );
};
