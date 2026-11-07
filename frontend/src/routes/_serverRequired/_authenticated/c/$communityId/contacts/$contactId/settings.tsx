import { createFileRoute } from "@tanstack/react-router";

import { ContactSettingsPage } from "@/pages/initiativeTools/contacts/ContactSettingsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/contacts/$contactId/settings"
)({
  component: ContactSettingsPage,
});
