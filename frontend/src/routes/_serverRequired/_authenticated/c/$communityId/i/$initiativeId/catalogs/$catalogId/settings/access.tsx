import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/catalogs/$catalogId/settings/access"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/toolSettings/ToolSettingsAccessPage").then((m) => ({
      default: m.ToolSettingsAccessPage,
    }))
  ),
});
