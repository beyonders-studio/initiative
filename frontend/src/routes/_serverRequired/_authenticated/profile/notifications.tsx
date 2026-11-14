import { createFileRoute } from "@tanstack/react-router";

import { useAuth } from "@/hooks/useAuth";
import { NotificationsPage } from "@/pages/my/settings/NotificationsPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/notifications")({
  component: NotificationsRoute,
});

function NotificationsRoute() {
  const { user, refreshUser } = useAuth();
  if (!user) return null;
  return <NotificationsPage user={user} refreshUser={refreshUser} />;
}
