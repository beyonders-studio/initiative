import { createFileRoute } from "@tanstack/react-router";

import { ConnectedPage } from "@/pages/community/plugins/ConnectedPage";

export const Route = createFileRoute("/plugins/connected")({
  component: ConnectedPage,
});
