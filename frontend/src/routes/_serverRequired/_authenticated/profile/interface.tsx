import { createFileRoute } from "@tanstack/react-router";

import { useAuth } from "@/hooks/useAuth";
import { InterfacePage } from "@/pages/my/settings/InterfacePage";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/interface")({
  component: InterfaceRoute,
});

function InterfaceRoute() {
  const { user, acceptUser } = useAuth();
  if (!user) return null;
  return <InterfacePage user={user} acceptUser={acceptUser} />;
}
