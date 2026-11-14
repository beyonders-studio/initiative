import { createFileRoute } from "@tanstack/react-router";

import { NotificationsPage } from "@/pages/my/NotificationsPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/notifications")({
  component: NotificationsPage,
});
