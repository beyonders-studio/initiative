import { createFileRoute } from "@tanstack/react-router";

import { IntakePage } from "@/pages/platform/IntakePage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/intake")({
  component: IntakePage,
});
