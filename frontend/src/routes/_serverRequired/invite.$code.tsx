import { createFileRoute } from "@tanstack/react-router";

import { InvitePage } from "@/pages/signIn/InvitePage";

export const Route = createFileRoute("/_serverRequired/invite/$code")({
  component: InvitePage,
});
