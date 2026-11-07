import { createFileRoute } from "@tanstack/react-router";

import { UserTrashPage } from "@/pages/user/settings/UserTrashPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/trash")({
  component: UserTrashPage,
});
