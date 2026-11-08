/**
 * The tabular twin of whatever a widget drew.
 *
 * Derived from the validated scene rather than from the widget, so it exists
 * for every widget — including ones this build has never seen — without any of
 * them doing anything. Rendered with the same trusted `TableNode` component a
 * `table` widget uses, so nothing new reaches the DOM.
 */

import { useTranslation } from "react-i18next";

import type { SceneNode } from "@/lib/widgets/sceneSpec";
import { sceneToTables } from "@/lib/widgets/sceneTable";

import { TableNode } from "./TableNode";

export function SceneTableView({ node }: { node: SceneNode }) {
  const { t } = useTranslation(["dashboards", "common"]);
  const tables = sceneToTables(node, t);

  if (!tables.length || tables.every((table) => table.rows.length === 0)) {
    return (
      <div className="flex h-full w-full items-center justify-center p-2 text-center">
        <p className="text-muted-foreground text-sm">{t("dashboards:tableView.empty")}</p>
      </div>
    );
  }

  return (
    <div className="h-full w-full overflow-auto">
      {tables.map((table, index) => (
        <TableNode
          // A stack's children have no identity of their own; position is what
          // the scene fixed and what the reader sees.
          // biome-ignore lint/suspicious/noArrayIndexKey: scene children are positional
          key={index}
          node={table}
        />
      ))}
    </div>
  );
}
