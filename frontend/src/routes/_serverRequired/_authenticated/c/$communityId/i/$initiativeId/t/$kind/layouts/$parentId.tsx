import { createFileRoute } from "@tanstack/react-router";

import { ToolPluginLayoutEditorPage } from "@/pages/community/tools/toolPlugins/ToolPluginLayoutEditorPage";

/** The layouts of a tool plug-in's item table under the row its items sit
 *  in, by the item's kind. */
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/t/$kind/layouts/$parentId"
)({
  // Which of its layouts the editor opens on: a list's kind, or the table's.
  validateSearch: (search: Record<string, unknown>) => ({
    layout: typeof search.layout === "string" ? search.layout : undefined,
  }),
  component: ToolPluginLayoutEditorPage,
});
