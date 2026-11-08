import { createFileRoute } from "@tanstack/react-router";

import { useAuth } from "@/hooks/useAuth";
import { UserSettingsNotificationsPage } from "@/pages/user/settings/UserSettingsNotificationsPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/notifications")({
  component: NotificationsPage,
});

function NotificationsPage() {
  const { user, refreshUser } = useAuth();
  if (!user) return null;
  return <UserSettingsNotificationsPage user={user} refreshUser={refreshUser} />;
}
