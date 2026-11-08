import { createFileRoute } from "@tanstack/react-router";

import { useAuth } from "@/hooks/useAuth";
import { AccountPage } from "@/pages/my/settings/account/AccountPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/account")({
  component: AccountRoute,
});

function AccountRoute() {
  const { user, logout } = useAuth();
  if (!user) return null;
  return <AccountPage user={user} logout={logout} />;
}
