import { createFileRoute } from "@tanstack/react-router";

import { CommunityContactsPage } from "@/pages/initiativeTools/contacts/ContactsPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId/contacts/")({
  component: CommunityContactsPage,
});
