import { createFileRoute } from "@tanstack/react-router";

import { CounterGroupPage } from "@/pages/community/tools/counterGroups/CounterGroupPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/counter-groups/$counterGroupId/"
)({
  component: CounterGroupPage,
});
