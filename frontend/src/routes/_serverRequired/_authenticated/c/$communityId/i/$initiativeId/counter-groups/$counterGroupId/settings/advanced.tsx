import { createFileRoute } from "@tanstack/react-router";

import { ToolSettingsAdvancedPage } from "@/pages/toolSettings/ToolSettingsAdvancedPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/counter-groups/$counterGroupId/settings/advanced"
)({
  component: ToolSettingsAdvancedPage,
});
