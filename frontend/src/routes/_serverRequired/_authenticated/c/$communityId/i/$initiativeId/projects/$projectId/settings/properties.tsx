import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/settings/properties"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/projects/ProjectSettingsPropertiesPage").then((m) => ({
      default: m.ProjectSettingsPropertiesPage,
    }))
  ),
});
