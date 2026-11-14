import { createFileRoute } from "@tanstack/react-router";

import { CounterPage } from "@/pages/community/tools/counterGroups/CounterPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/counter-groups/$counterGroupId/counter/$counterId"
)({
  component: CounterPage,
});
