import { createFileRoute } from "@tanstack/react-router";

import { LazyInitiativeDetailPage } from "@/lib/initiativeDetailRoute";
import { validateInitiativeToolSearch } from "@/lib/routeSearch";

/** A tool plug-in's tab on its initiative's page, by the tool's kind. */
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/t/$kind/"
)({
  validateSearch: validateInitiativeToolSearch,
  component: function ToolPluginTab() {
    return <LazyInitiativeDetailPage tool={Route.useParams().kind} />;
  },
});
