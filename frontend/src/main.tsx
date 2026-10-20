import "./styles.css";
import "./i18n";

import { Capacitor } from "@capacitor/core";
import { SplashScreen } from "@capacitor/splash-screen";
import { CapacitorUpdater } from "@capgo/capacitor-updater";
import { QueryClientProvider } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { RouterProvider } from "@tanstack/react-router";
import React, { Suspense } from "react";
import ReactDOM from "react-dom/client";

import { setApiBaseUrl } from "@/api/client";
import { TaskCompletionEffectHost } from "@/components/effects/TaskCompletionEffectHost";
import { AppErrorBoundary } from "@/components/errors/AppErrorBoundary";
import { AuthProvider, useAuth } from "@/hooks/useAuth";
import { CommunityProvider, useCommunities } from "@/hooks/useCommunities";
import { KeepScreenAwakeProvider } from "@/hooks/useKeepScreenAwake";
import { PrideProvider } from "@/hooks/usePride";
import { useRouteGuardSync } from "@/hooks/useRouteGuardSync";
import { ServerProvider, useServer } from "@/hooks/useServer";
import { ThemeProvider } from "@/hooks/useTheme";
import { prepareOfflineCache } from "@/lib/offlineBoot";
import { bindOnlineManagerToDevice } from "@/lib/onlineStatus";
import { queryClient } from "@/lib/queryClient";
import { adoptStoredServerUrl } from "@/lib/serverStorage";
import { initStorage } from "@/lib/storage";
import { sellsOnThisDevice } from "@/lib/storeSelling";
import { router } from "@/router";
import { registerServiceWorker } from "@/serviceWorkerRegistration";

/**
 * Inner app component that provides router context from hooks.
 * Must be inside all providers to access their contexts.
 */
const InnerApp = () => {
  const auth = useAuth();
  const communities = useCommunities();
  const server = useServer();

  // Auth and server state settle after the first router load, so ask the router
  // to re-run its `beforeLoad` guards when they do — that keeps redirects at the
  // navigation layer instead of the render path.
  useRouteGuardSync(router, auth, server);

  return (
    <>
      <RouterProvider
        router={router}
        context={{
          queryClient,
          auth,
          communities,
          server,
        }}
      />
      <TaskCompletionEffectHost />
    </>
  );
};

async function bootstrap() {
  await initStorage();

  // What this device last loaded, if it is still ours and still fresh. Decided
  // before render so a launch with no signal has its content in hand rather
  // than waiting on a request that will not answer.
  const offlinePersist = await prepareOfflineCache();

  // On native, set the API base URL immediately from storage so requests
  // reach the real backend before React effects run (avoids race condition
  // where child provider effects fire before ServerProvider's useEffect).
  if (Capacitor.isNativePlatform()) {
    // Confirm this web bundle booted so the OTA updater doesn't roll it back. If an applied
    // bundle never reaches this point within appReadyTimeout, Capgo reverts to the last-good
    // bundle on next launch (see capacitor.config.ts → CapacitorUpdater). Best-effort.
    try {
      await CapacitorUpdater.notifyAppReady();
    } catch (error) {
      console.debug("notifyAppReady failed (updater unavailable):", error);
    }

    // Drop the native splash now that this bundle is alive. It is kept up (launchAutoHide off)
    // to cover both cold start and the OTA bundle swap that useNativeUpdate raises before
    // CapacitorUpdater.set() reloads the WebView. Always hide it — even if notifyAppReady threw
    // above — so a failure there can't strand the user on the splash. Best-effort.
    try {
      await SplashScreen.hide();
    } catch (error) {
      console.debug("SplashScreen.hide failed (plugin unavailable):", error);
    }

    setApiBaseUrl(adoptStoredServerUrl());

    // Ask the store early, so plan wording and buttons are settled by the time
    // anything shows them. Not awaited: nothing waits on it to render.
    void sellsOnThisDevice();

    // Before the first query runs: a restored cache is only worth having if
    // React Query leaves it on screen instead of refetching over it while
    // there is no network to refetch from. Awaited so the device's answer is
    // in hand before anything can ask — bounded internally, so a plugin that
    // does not answer delays boot rather than ending it.
    await bindOnlineManagerToDevice();
  }

  const withQueryClient = (children: React.ReactNode) =>
    offlinePersist ? (
      <PersistQueryClientProvider client={queryClient} persistOptions={offlinePersist}>
        {children}
      </PersistQueryClientProvider>
    ) : (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>
      <Suspense fallback={null}>
        <AppErrorBoundary>
          <ThemeProvider>
            <PrideProvider>
              <KeepScreenAwakeProvider>
                <ServerProvider>
                  {withQueryClient(
                    <AuthProvider>
                      <CommunityProvider>
                        <InnerApp />
                      </CommunityProvider>
                    </AuthProvider>
                  )}
                </ServerProvider>
              </KeepScreenAwakeProvider>
            </PrideProvider>
          </ThemeProvider>
        </AppErrorBoundary>
      </Suspense>
    </React.StrictMode>
  );

  if (import.meta.env.PROD) {
    registerServiceWorker();
  }
}

void bootstrap();
