import { createFileRoute } from "@tanstack/react-router";

import { ToolSettingsAccessPage } from "@/pages/toolSettings/ToolSettingsAccessPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/counter-groups/$counterGroupId/settings/access"
)({
  component: ToolSettingsAccessPage,
});
