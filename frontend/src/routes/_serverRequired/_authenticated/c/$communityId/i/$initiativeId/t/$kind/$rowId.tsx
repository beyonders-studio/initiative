import { createFileRoute } from "@tanstack/react-router";

import { ToolPluginRowPage } from "@/pages/community/tools/toolPlugins/ToolPluginRowPage";

/** One row of a tool plug-in, the tool's own or an item's, by its kind.
 *  `focus` names the counter field it is open full screen on. */
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/t/$kind/$rowId"
)({
  validateSearch: (search: Record<string, unknown>): { focus?: string } => ({
    focus: typeof search.focus === "string" ? search.focus : undefined,
  }),
  component: ToolPluginRowPage,
});
