/**
 * `/t/$kind/layouts` and `/t/$kind/layouts/$parentId` — a tool plug-in's
 * table's layouts where its rows are listed, edited in place as a built-in
 * tool's are: the tool's own rows' in their initiative, and an item table's
 * under the row its items sit in. Its lists and its rows' page start as its
 * plug-in declares them, drawn with the rows they list, and name the table's
 * own fields. `?layout=` opens on one of them.
 *
 * Who may is the server's answer on the set: the initiative's managers for the
 * tool's own rows, and for an item's whoever may configure the row it sits in.
 * The editor itself says when the screen is too narrow to edit on.
 */

import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { ListLayoutReadKind } from "@/api/generated/initiativeAPI.schemas";
import { ActionsPreview, regionsOf } from "@/components/layouts/details";
import { SettingsPermissionRequired } from "@/components/settings/SettingsPermissionRequired";
import { itemSaves } from "@/hooks/useFieldSave";
import { LAYOUT_NAMESPACES } from "@/hooks/useLayoutEnv";
import {
  pluginToolRowSaves,
  useInstalledTools,
  usePluginToolRows,
} from "@/hooks/usePluginToolRows";
import { usePropertyEnv } from "@/hooks/usePropertyEnv";
import { useRouteId } from "@/hooks/useRouteId";
import { useSaveLayouts, useToolLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import {
  type InstalledTool,
  type ToolTable,
  toolLayoutTarget,
  toolOfKind,
  toolPluginListRoute,
  toolPluginRowRoute,
  toolRow,
  toolText,
} from "@/lib/toolPlugins";
import { initiativeRoute } from "@/lib/tools";
import type { TranslateFn } from "@/types/i18n";
import { DetailLayoutView } from "@/ui/layouts/DetailLayoutView";
import { cardOf, columnsOf, type ListShape } from "@/ui/layouts/draft";
import { type EditableDetail, type EditableLists, LayoutEditor } from "@/ui/layouts/LayoutEditor";
import { setOf } from "@/ui/layouts/layoutSet";
import type { LayoutNode } from "@/ui/layouts/tree";

import { NAME_CARD, ToolRows } from "./ToolRows";
import { toolDetail } from "./toolDetail";
import { toolFields } from "./toolFields";

const noop = () => {};

/** The words of a table's rows' page, in `plugins`. */
const PAGE_WORDS: EditableDetail["words"] = {
  name: "plugins:tool.layout.name",
  help: "plugins:tool.layout.help",
  shipped: "plugins:tool.layout.shipped",
  titleHelp: "plugins:tool.layout.titleHelp",
  hiddenHelp: "plugins:tool.layout.hiddenHelp",
  parts: "plugins:tool.layout.",
};

/** The editor over one table found, in the place its rows are listed. */
const TableLayoutEditor = ({
  tool,
  table,
  initiativeId,
  parentId,
  initialKind,
}: {
  tool: InstalledTool;
  table: ToolTable;
  initiativeId: number;
  parentId: number | null;
  initialKind?: string;
}) => {
  const navigate = useNavigate();
  const gp = useCommunityPath();
  const { t, i18n } = useTranslation([...LAYOUT_NAMESPACES, "plugins"]);
  const language = i18n.language;

  const target = useMemo(
    () => toolLayoutTarget(table.kind, initiativeId, parentId),
    [table.kind, initiativeId, parentId]
  );
  const set = useToolLayouts(target).data;
  const save = useSaveLayouts(target);
  const listed = usePluginToolRows(
    table,
    parentId === null ? { initiative_id: initiativeId } : { parent_id: parentId }
  );
  const rows = useMemo(() => (listed.data?.items ?? []).map(toolRow), [listed.data]);
  // Its rows hold none of the initiative's properties, so none is made here.
  const { definitions } = usePropertyEnv({ initiativeId, enabled: true });
  const propertyEnv = useMemo(() => ({ definitions }), [definitions]);
  const fields = useMemo(() => toolFields(table, language), [table, language]);

  const lists = useMemo<EditableLists>(() => {
    const declared = (kind: ListLayoutReadKind) =>
      table.layouts.lists.find((each) => each.kind === kind);
    // Each list draws as its plug-in ships it: its own card or columns.
    const shape = (kind: ListLayoutReadKind): ListShape => ({
      card: (declared(kind)?.card as LayoutNode | null | undefined) ?? NAME_CARD,
      columns: declared(kind)?.columns ?? ["name"],
      columnFields: new Set(fields.keys()),
    });
    return {
      fields: () => new Map(fields),
      shape,
      help: (kind) => `plugins:tool.layout.lists.${kind}`,
      preview: ({ layout, fields: shown, frame }) => {
        const shipped = declared(layout.kind);
        const { kind: _kind, ...definition } = shipped ?? { kind: layout.kind };
        return frame(
          <ToolRows
            tool={tool}
            table={table}
            list={{
              kind: layout.kind,
              is_default: false,
              hidden: false,
              updated_at: null,
              definition: {
                ...definition,
                ...setOf(layout.definition),
                card: cardOf(layout.definition, shown, layout.shape) as never,
                columns: columnsOf(layout.definition, shown, layout.shape),
              },
            }}
            rows={rows}
            initiativeId={initiativeId}
            sorting={[]}
            onSortingChange={noop}
            editing
          />
        );
      },
    };
  }, [tool, table, fields, rows, initiativeId]);

  const details = useMemo<EditableDetail[]>(() => {
    const detail = toolDetail(table, language);
    const first = rows[0];
    return [
      {
        spec: detail.spec,
        words: PAGE_WORDS,
        typeName: toolText(table.name, language),
        fields: detail.fields,
        preview: (tree) =>
          first ? (
            <DetailLayoutView
              detail={detail}
              item={first}
              layout={regionsOf(tree)}
              editing
              context={{
                readOnly: false,
                initiativeId,
                saves: itemSaves(pluginToolRowSaves(table.kind), first.id),
                actions: <ActionsPreview />,
              }}
            />
          ) : listed.isSuccess ? (
            <p className="text-muted-foreground text-sm">{t("plugins:tool.layout.noItems")}</p>
          ) : null,
      },
    ];
  }, [table, language, rows, listed.isSuccess, initiativeId, t]);

  if (!set) return null;
  if (!set.can_configure) {
    return <SettingsPermissionRequired scope={parentId === null ? "initiative" : "tool"} />;
  }
  return (
    <LayoutEditor
      // Another place's editor starts afresh: a draft, and the question before
      // leaving it, belong to the place they were made for.
      key={`${table.kind}:${parentId ?? initiativeId}`}
      t={t as TranslateFn}
      initiativeId={initiativeId}
      lists={lists}
      details={details}
      propertyEnv={propertyEnv}
      layouts={set}
      save={save.mutateAsync}
      metadataHref={gp(`${initiativeRoute(initiativeId)}/settings/properties`)}
      initialKind={initialKind}
      onClose={() =>
        void navigate({
          to: gp(
            parentId === null || table.parent === null
              ? toolPluginListRoute(initiativeId, table.kind)
              : toolPluginRowRoute(initiativeId, table.parent, parentId)
          ),
        })
      }
    />
  );
};

export const ToolPluginLayoutEditorPage = () => {
  const { kind = "" } = useParams({ strict: false }) as { kind?: string };
  const { layout } = useSearch({ strict: false }) as { layout?: string };
  const initiativeId = useRouteId("initiativeId");
  const parentId = useRouteId("parentId");
  const installs = useInstalledTools();
  const found = installs.status === "ready" ? toolOfKind(installs.tools, kind) : null;
  // An item table's layouts are under a row, and the tool's own under none.
  if (!found || initiativeId === null || (found.table.parent === null) !== (parentId === null)) {
    return null;
  }
  return (
    <TableLayoutEditor
      tool={found.tool}
      table={found.table}
      initiativeId={initiativeId}
      parentId={parentId}
      initialKind={layout}
    />
  );
};
