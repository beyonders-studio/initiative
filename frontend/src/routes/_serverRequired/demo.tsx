import { createFileRoute } from "@tanstack/react-router";

import { DemoPage } from "@/pages/DemoPage";

export const Route = createFileRoute("/_serverRequired/demo")({
  component: DemoPage,
});
