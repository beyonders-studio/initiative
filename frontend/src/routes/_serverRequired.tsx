import { createFileRoute, Outlet, redirect, useLocation } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";

import { NativeUpdateRequiredDialog } from "@/components/NativeUpdateRequiredDialog";
import { UpdateReadyToast } from "@/components/UpdateReadyToast";
import { useNativeUpdate } from "@/hooks/useNativeUpdate";
import { useServer } from "@/hooks/useServer";

const FullScreenLoader = () => (
  <div className="flex min-h-app items-center justify-center">
    <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
  </div>
);

/**
 * Layout route that requires a server to be configured on native platforms.
 * On web, this passes through. On mobile without a configured server, sends
 * everything but sign-in to sign-in, which asks for one.
 */
export const Route = createFileRoute("/_serverRequired")({
  beforeLoad: ({ context, location }) => {
    const { server } = context;
    // An app with no server signs in first, and sign-in asks for one.
    if (
      !server?.loading &&
      server?.isNativePlatform &&
      !server.isServerConfigured &&
      location.pathname !== "/login"
    ) {
      throw redirect({ to: "/login" });
    }
  },
  component: ServerRequiredLayout,
});

function ServerRequiredLayout() {
  const { loading, isNativePlatform, isServerConfigured } = useServer();
  const pathname = useLocation({ select: (location) => location.pathname });
  // OTA live updates (native only). Mounted here — once a server is configured but before
  // auth is required — so a fresh install can update its web bundle even from the login screen.
  const {
    updateReady,
    applyUpdate,
    dismissUpdate,
    nativeUpdateRequired,
    dismissNativeUpdateRequired,
  } = useNativeUpdate();

  // Show loading state while server context initializes
  if (loading) {
    return <FullScreenLoader />;
  }

  // On native with no server configured, anywhere but sign-in, the
  // redirect belongs to `beforeLoad` above, which re-runs once the server
  // context settles (``useRouteGuardSync``). Hold the loader until it lands
  // rather than redirecting from the render path — a rendered `<Navigate>`
  // re-navigates on every render and stops only because this layout unmounts.
  if (isNativePlatform && !isServerConfigured && pathname !== "/login") {
    return <FullScreenLoader />;
  }

  return (
    <>
      <Outlet />
      <UpdateReadyToast
        open={updateReady.show}
        version={updateReady.version}
        onClose={dismissUpdate}
        onReload={applyUpdate}
      />
      <NativeUpdateRequiredDialog
        open={nativeUpdateRequired.show}
        version={nativeUpdateRequired.version}
        minNativeVersion={nativeUpdateRequired.minNativeVersion}
        onClose={dismissNativeUpdateRequired}
      />
    </>
  );
}
