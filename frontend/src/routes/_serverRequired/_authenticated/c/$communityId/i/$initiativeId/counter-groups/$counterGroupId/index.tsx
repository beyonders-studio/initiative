import { createFileRoute } from "@tanstack/react-router";

import { CounterGroupDetailPage } from "@/pages/initiativeTools/counters/CounterGroupDetailPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/counter-groups/$counterGroupId/"
)({
  component: CounterGroupDetailPage,
});
