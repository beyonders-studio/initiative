import { createFileRoute } from "@tanstack/react-router";

import { CommunityContactsPage } from "@/pages/community/tools/contacts/ContactsPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId/contacts/")({
  component: CommunityContactsPage,
});
