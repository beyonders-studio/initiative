import { createFileRoute } from "@tanstack/react-router";

import { InitiativePluginRoute } from "@/pages/community/plugins/PluginRoute";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/plugins/$pluginId"
)({
  component: InitiativePluginRoute,
});
