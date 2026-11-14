import { createFileRoute } from "@tanstack/react-router";

import { StoragePage } from "@/pages/platform/StoragePage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/storage")({
  component: StoragePage,
});
