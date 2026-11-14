import { createFileRoute } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { SettingsLayout } from "@/pages/community/tools/settings/SettingsLayout";

// A contact's name and how to reach them are edited on its own page, and it
// carries no description.
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/contacts/$contactId/settings"
)({
  component: () => <SettingsLayout tool={Tool.contact} detailsForm={false} />,
});
