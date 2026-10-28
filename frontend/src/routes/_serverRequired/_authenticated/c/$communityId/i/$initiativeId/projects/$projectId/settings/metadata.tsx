import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/settings/metadata"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/projects/ProjectSettingsMetadataPage").then((m) => ({
      default: m.ProjectSettingsMetadataPage,
    }))
  ),
});
