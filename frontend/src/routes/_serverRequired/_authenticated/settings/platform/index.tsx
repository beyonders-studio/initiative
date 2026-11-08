import { createFileRoute } from "@tanstack/react-router";

import { IndexPage } from "@/pages/platform/IndexPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/")({
  component: IndexPage,
});
