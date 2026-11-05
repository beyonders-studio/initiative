import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/contacts/$contactId/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/contacts/ContactSettingsPage").then((m) => ({
      default: m.ContactSettingsPage,
    }))
  ),
});
