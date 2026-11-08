import { createFileRoute } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolSettingsPage } from "@/pages/toolSettings/ToolSettingsPage";

// A contact's name and how to reach them are edited on its own page, and it
// carries no description.
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/contacts/$contactId/settings"
)({
  component: () => <ToolSettingsPage tool={Tool.contact} detailsForm={false} />,
});
