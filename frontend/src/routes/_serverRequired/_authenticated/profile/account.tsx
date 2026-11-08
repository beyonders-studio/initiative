import { createFileRoute } from "@tanstack/react-router";

import { useAuth } from "@/hooks/useAuth";
import { UserSettingsAccountPage } from "@/pages/user/settings/UserSettingsAccountPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/account")({
  component: AccountPage,
});

function AccountPage() {
  const { user, logout } = useAuth();
  if (!user) return null;
  return <UserSettingsAccountPage user={user} logout={logout} />;
}
