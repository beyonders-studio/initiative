import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { Suspense } from "react";

import { CookieConsent } from "@/components/account/CookieConsent";
import { AgeGateDialog } from "@/components/auth/AgeGateDialog";
import { SecondFactorStepUpDialog } from "@/components/auth/SecondFactorStepUpDialog";
import { StepUpDialog } from "@/components/auth/StepUpDialog";
import { HelpHost } from "@/components/help/HelpHost";
import { DesktopTitleBar } from "@/components/navigation/DesktopTitleBar";
import { useAnalytics } from "@/hooks/useAnalytics";
import { useClockSync } from "@/hooks/useClockSync";
import { useColorTheme } from "@/hooks/useColorTheme";
import { useConsentSync } from "@/hooks/useConsentSync";
import { useDeepLinks } from "@/hooks/useDeepLinks";
import { useDesktopTray } from "@/hooks/useDesktopApp";
import { useInterfaceColors } from "@/hooks/useInterfaceColors";
import { useSafeArea } from "@/hooks/useSafeArea";
import { useShareTarget } from "@/hooks/useShareTarget";
import type { RouterContext } from "@/router";

/**
 * Loading fallback for lazy-loaded pages.
 */
const PageLoader = () => (
  <div className="flex items-center justify-center py-20">
    <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
  </div>
);

/**
 * Root component that handles global hooks.
 */
const RootComponent = () => {
  // Global hooks
  useInterfaceColors();
  useColorTheme();
  useConsentSync();
  useAnalytics();
  useSafeArea();
  useDeepLinks();
  useShareTarget();
  useDesktopTray();
  useClockSync();

  return (
    <>
      {/* Over every screen, sign-in included: the desktop app has no other title bar. */}
      <DesktopTitleBar />
      <Suspense fallback={<PageLoader />}>
        <Outlet />
      </Suspense>
      <StepUpDialog />
      <SecondFactorStepUpDialog />
      <AgeGateDialog />
      <CookieConsent />
      <HelpHost />
    </>
  );
};

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootComponent,
});
