import { createFileRoute } from "@tanstack/react-router";

import { SharePage } from "@/pages/SharePage";

export const Route = createFileRoute("/_serverRequired/_authenticated/share")({
  component: SharePage,
});
