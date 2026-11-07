import { createFileRoute } from "@tanstack/react-router";

import { PluginConnectedPage } from "@/pages/plugins/PluginConnectedPage";

export const Route = createFileRoute("/plugins/connected")({
  component: PluginConnectedPage,
});
