import { createFileRoute } from "@tanstack/react-router";

import { useAuth } from "@/hooks/useAuth";
import { ProfilePage } from "@/pages/my/settings/profile/ProfilePage";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/")({
  component: ProfileIndexPage,
});

function ProfileIndexPage() {
  const { user, refreshUser } = useAuth();
  if (!user) return null;
  return <ProfilePage user={user} refreshUser={refreshUser} />;
}
