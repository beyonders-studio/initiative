import { createFileRoute } from "@tanstack/react-router";

import { CommunityPluginRoute } from "@/pages/plugins/CommunityPluginRoute";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/plugins_/$pluginId"
)({
  component: CommunityPluginRoute,
});
