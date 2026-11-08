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

import { useNavigate, useSearch } from "@tanstack/react-router";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { InitiativeSettingsPropertiesTab } from "@/components/initiatives/InitiativeSettingsPropertiesTab";
import { fileDetail } from "@/components/layouts/details";
import { SettingsPermissionRequired } from "@/components/settings/SettingsPermissionRequired";
import { useCollection, useCollectionFilesFeed } from "@/hooks/useCollections";
import { LAYOUT_NAMESPACES } from "@/hooks/useLayoutEnv";
import { usePropertyEnv } from "@/hooks/usePropertyEnv";
import { useRouteId } from "@/hooks/useRouteId";
import { instanceTarget, useInstanceLayouts, useSaveLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import { collectionFileFields, FILE_LIST_SHAPE } from "@/lib/layouts/files";
import { collectionRoute, initiativeRoute } from "@/lib/tools";
import type { ToolIndexRow } from "@/pages/community/tools/ToolIndexPage";
import { ToolIndexTable } from "@/pages/community/tools/ToolIndexTable";
import type { TranslateFn } from "@/types/i18n";
import { withDisplays } from "@/ui/layouts/fields";
import { type EditableLists, LayoutEditor } from "@/ui/layouts/LayoutEditor";

import { type CollectionList, CollectionListView } from "./collectionLists";

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

export const LayoutEditorPage = () => {
  const { layout } = useSearch({ strict: false }) as { layout?: string };
  const id = useRouteId("collectionId");
  const navigate = useNavigate();
  const gp = useCommunityPath();
  const { t } = useTranslation(LAYOUT_NAMESPACES);

  const collection = useCollection(id).data;
  const set = useInstanceLayouts("collection", id).data;
  const save = useSaveLayouts(instanceTarget("collection", id ?? 0));
  const feed = useCollectionFilesFeed(id, NEWEST_ADDED);
  const propertyEnv = usePropertyEnv({
    initiativeId: collection?.initiative_id ?? null,
    enabled: true,
  });
  const files = useMemo(() => feed.data?.pages[0]?.items ?? [], [feed.data]);
  const rows = useMemo(
    () => files.map((file) => ({ ...file, card: null }) as ToolIndexRow),
    [files]
  );
  const lists = useMemo<EditableLists | null>(
    () =>
      collection
        ? {
            fields: (definitions) => collectionFileFields(collection.metadata, definitions),
            shape: FILE_LIST_SHAPE,
            owner: { kind: "collection", id: collection.id },
            help: (kind) => `files:collections.listHelp.${kind}`,
            preview: ({ layout, fields, frame }) =>
              frame(
                <CollectionListView
                  kind={layout.kind as CollectionList}
                  definition={layout.definition}
                  fields={withDisplays(fields, layout.definition.displays)}
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
    [collection, files, rows]
  );
  const details = useMemo(
    () => (collection ? [fileDetail(collection, files[0], feed.isSuccess)] : []),
    [collection, files, feed.isSuccess]
  );

  if (!collection || !set || !lists) return null;
  if (!set.can_configure) return <SettingsPermissionRequired scope="tool" />;
  return (
    <LayoutEditor
      // Another collection's editor starts afresh: a draft, and the question
      // before leaving it, belong to the collection they were made for.
      key={collection.id}
      t={t as TranslateFn}
      initiativeId={collection.initiative_id}
      lists={lists}
      details={details}
      propertyEnv={propertyEnv}
      layouts={set}
      save={save.mutateAsync}
      properties={(placement) => (
        <InitiativeSettingsPropertiesTab
          initiativeId={collection.initiative_id}
          owner={{ kind: "collection", id: collection.id }}
          canManage={collection.can.edit}
          placement={placement}
        />
      )}
      metadataHref={gp(`${initiativeRoute(collection.initiative_id)}/settings/properties`)}
      initialKind={layout}
      onClose={() =>
        void navigate({ to: gp(collectionRoute(collection.initiative_id, collection.id)) })
      }
    />
  );
};
