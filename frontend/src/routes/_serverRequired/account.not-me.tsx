import { createFileRoute } from "@tanstack/react-router";

import { NotMePage } from "@/pages/signIn/NotMePage";

export const Route = createFileRoute("/_serverRequired/account/not-me")({
  component: NotMePage,
});
