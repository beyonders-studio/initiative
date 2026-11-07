import { createFileRoute } from "@tanstack/react-router";

import { CounterDetailPage } from "@/pages/initiativeTools/counters/CounterDetailPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/counter-groups/$counterGroupId/counter/$counterId"
)({
  component: CounterDetailPage,
});
