import { createFileRoute } from "@tanstack/react-router";

import { ToolSettingsAdvancedPage } from "@/pages/toolSettings/ToolSettingsAdvancedPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/posts/$postId/settings/advanced"
)({
  component: ToolSettingsAdvancedPage,
});
