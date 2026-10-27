import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/libraries/$libraryId/settings/layouts"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/toolSettings/ToolSettingsLayoutsPage").then((m) => ({
      default: m.ToolSettingsLayoutsPage,
    }))
  ),
});
