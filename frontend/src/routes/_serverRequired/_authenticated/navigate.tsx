import { createFileRoute } from "@tanstack/react-router";

import { NavigatePage } from "@/pages/NavigatePage";

export const Route = createFileRoute("/_serverRequired/_authenticated/navigate")({
  component: NavigatePage,
});
