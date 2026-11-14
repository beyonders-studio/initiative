import { createFileRoute } from "@tanstack/react-router";

import { UsersPage } from "@/pages/operator/users/UsersPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/operator/")({
  component: UsersPage,
});
