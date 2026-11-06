import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/contacts/$contactId/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/contacts/ContactSettingsPage").then((m) => ({
      default: m.ContactSettingsPage,
    }))
  ),
});
