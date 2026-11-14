import { createFileRoute } from "@tanstack/react-router";

import { PluginRoute } from "@/pages/community/plugins/PluginRoute";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/plugins_/$pluginId"
)({
  component: PluginRoute,
});
