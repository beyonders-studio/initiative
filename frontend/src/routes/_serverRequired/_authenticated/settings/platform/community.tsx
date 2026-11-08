import { createFileRoute } from "@tanstack/react-router";

import { CommunityPage } from "@/pages/platform/CommunityPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/community")(
  {
    component: CommunityPage,
  }
);
