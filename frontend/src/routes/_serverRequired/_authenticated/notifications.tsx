import { createFileRoute } from "@tanstack/react-router";

import { NotificationsInboxPage } from "@/pages/user/NotificationsInboxPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/notifications")({
  component: NotificationsInboxPage,
});
