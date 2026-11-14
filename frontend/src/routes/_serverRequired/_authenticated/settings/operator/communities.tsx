import { createFileRoute } from "@tanstack/react-router";

import { CommunitiesPage } from "@/pages/operator/communities/CommunitiesPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/settings/operator/communities"
)({
  component: CommunitiesPage,
});
