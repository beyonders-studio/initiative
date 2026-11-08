import { createFileRoute } from "@tanstack/react-router";

import { useAuth } from "@/hooks/useAuth";
import { UserSettingsProfilePage } from "@/pages/user/settings/UserSettingsProfilePage";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/")({
  component: ProfileIndexPage,
});

function ProfileIndexPage() {
  const { user, refreshUser } = useAuth();
  if (!user) return null;
  return <UserSettingsProfilePage user={user} refreshUser={refreshUser} />;
}
