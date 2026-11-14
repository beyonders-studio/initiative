import { createFileRoute } from "@tanstack/react-router";

import { PushPage } from "@/pages/platform/PushPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/push")({
  component: PushPage,
});
