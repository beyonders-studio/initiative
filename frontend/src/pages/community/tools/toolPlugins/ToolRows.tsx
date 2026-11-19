import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { LAYOUT_NAMESPACES } from "@/hooks/useLayoutEnv";
import { useCommunityPath } from "@/lib/communityUrl";
import {
  type ToolListLayout,
  type ToolRow,
  type ToolTable,
  toolPluginRowRoute,
} from "@/lib/toolPlugins";
import type { TranslateFn } from "@/types/i18n";
import { Card, CardContent } from "@/ui/card";
import { DataTable } from "@/ui/data-table";
import { fieldColumn } from "@/ui/layouts/columns";
import { type LayoutEnv, withDisplays } from "@/ui/layouts/fields";
import { type LayoutContext, type LayoutNode, LayoutTree } from "@/ui/layouts/tree";

import { toolFields } from "./toolFields";

/** What a grid draws where its layout names no card: the row's name. */
const NAME_CARD: LayoutNode = {
  type: "card",
  children: [{ type: "field", props: { field: "name" } }],
};

/**
 * A table's rows, drawn as one of its list layouts says: a grid of its card,
 * or a table of its columns, each field in its kind's look and each scale or
 * counter as the layout's `displays` say. A row's name opens its page. Which
 * layout is the page's to pick, as a built-in tool's list picks its view.
 */
export const ToolRows = ({
  table,
  list,
  rows,
  initiativeId,
}: {
  table: ToolTable;
  list: ToolListLayout;
  rows: ToolRow[];
  initiativeId: number;
}) => {
  const { t, i18n } = useTranslation(["plugins", "common", ...LAYOUT_NAMESPACES]);
  const communityPath = useCommunityPath();
  const fields = useMemo(
    () => withDisplays(toolFields(table, i18n.language), list.displays),
    [table, i18n.language, list.displays]
  );
  const env = useMemo<LayoutEnv<ToolRow>>(
    () => ({
      t: t as TranslateFn,
      communityPath,
      itemHref: (row) => communityPath(toolPluginRowRoute(initiativeId, table.kind, row.id)),
    }),
    [t, communityPath, initiativeId, table.kind]
  );

  const columns = useMemo(
    () =>
      list.kind === "table"
        ? (list.columns ?? ["name"]).flatMap((id) => {
            const field = fields.get(id);
            return field ? [fieldColumn(field, env, { sortFn: "alphanumeric" })] : [];
          })
        : [],
    [list.kind, list.columns, fields, env]
  );
  const view = useMemo<LayoutContext<ToolRow>>(
    () => ({ fields, variant: "card", env }),
    [fields, env]
  );

  if (list.kind === "table") {
    return <DataTable columns={columns} data={rows} getRowId={(row) => String(row.id)} />;
  }
  const card = (list.card as LayoutNode | null | undefined) ?? NAME_CARD;
  return (
    <ul className="grid grid-cols-fill-56/4 gap-3">
      {rows.map((row) => (
        <li key={row.id}>
          <Card className="h-full">
            <CardContent className="space-y-2 p-4">
              <LayoutTree node={card} item={row} view={view} />
            </CardContent>
          </Card>
        </li>
      ))}
    </ul>
  );
};
