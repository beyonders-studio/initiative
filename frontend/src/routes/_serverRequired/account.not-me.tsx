import { createFileRoute } from "@tanstack/react-router";

import { AccountNotMePage } from "@/pages/AccountNotMePage";

export const Route = createFileRoute("/_serverRequired/account/not-me")({
  component: AccountNotMePage,
});
