import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/roles"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsCommunityRolesPage").then((m) => ({
      default: m.SettingsCommunityRolesPage,
    }))
  ),
});
