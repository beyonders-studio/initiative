import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { Suspense } from "react";

import { AgeGateDialog } from "@/components/auth/AgeGateDialog";
import { SecondFactorStepUpDialog } from "@/components/auth/SecondFactorStepUpDialog";
import { StepUpDialog } from "@/components/auth/StepUpDialog";
import { CookieConsent } from "@/components/CookieConsent";
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
      <Suspense fallback={<PageLoader />}>
        <Outlet />
      </Suspense>
      <StepUpDialog />
      <SecondFactorStepUpDialog />
      <AgeGateDialog />
      <CookieConsent />
    </>
  );
};

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootComponent,
});
