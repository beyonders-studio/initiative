import { createFileRoute } from "@tanstack/react-router";

import { IndexPage } from "@/pages/community/settings/IndexPage";

// No page of its own: `/settings` sends each person to the first tab they may
// open — see IndexPage.
export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId/settings/")({
  component: IndexPage,
});
