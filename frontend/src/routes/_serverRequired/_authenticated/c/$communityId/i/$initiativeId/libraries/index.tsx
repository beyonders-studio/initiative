import { createFileRoute } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { LazyInitiativeDetailPage } from "@/lib/initiativeDetailRoute";
import { validateInitiativeToolSearch } from "@/lib/routeSearch";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/libraries/"
)({
  validateSearch: validateInitiativeToolSearch,
  component: () => <LazyInitiativeDetailPage tool={Tool.library} />,
});
