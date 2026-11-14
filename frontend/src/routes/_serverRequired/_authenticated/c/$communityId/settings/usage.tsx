import { createFileRoute } from "@tanstack/react-router";

import { UsagePage } from "@/pages/community/settings/usage/UsagePage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/usage"
)({
  component: UsagePage,
});
