import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { validateId } from "@/lib/routeSearch";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/integrations"
)({
  /** `plugin` opens that install's row: where a version waiting for the
   *  seat's answer links to. */
  validateSearch: (search: Record<string, unknown>): { plugin?: number } => ({
    plugin: validateId(search.plugin),
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsCommunityIntegrationsPage").then((m) => ({
      default: m.SettingsCommunityIntegrationsPage,
    }))
  ),
});
