import { createFileRoute } from "@tanstack/react-router";

import { TrashPage } from "@/pages/my/settings/TrashPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/trash")({
  component: TrashPage,
});
