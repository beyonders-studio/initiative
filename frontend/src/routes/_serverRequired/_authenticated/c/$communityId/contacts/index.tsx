import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId/contacts/")({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/contacts/ContactsPage").then((m) => ({
      default: m.CommunityContactsPage,
    }))
  ),
});
