import { Capacitor } from "@capacitor/core";
import { lazy, Suspense } from "react";
import { useTranslation } from "react-i18next";

import { AUTH_STEP_UP_EVENT, type StepUpEventDetail } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAuthChallenge } from "@/hooks/useAuthChallenge";
import { useCommunityLoginProviders, useLoginProviders } from "@/hooks/useCommunityAuthPolicy";
import { providerSignInHref } from "@/lib/returnPath";

// The providers' marks load when the dialog first shows one, not with every page.
const ProviderMark = lazy(() =>
  import("@/components/auth/ProviderMark").then((m) => ({ default: m.ProviderMark }))
);

/** The path the sign-in should return to: where the challenge happened. */
const currentSpaPath = (): string => `${window.location.pathname}${window.location.search}`;

/**
 * Global handler for community sign-in requirements. When any request is refused
 * with `COMMUNITY_AUTH_STEP_UP_REQUIRED` (dispatched by the API client as a
 * window event carrying the required provider's slug), this dialog offers
 * that provider's sign-in and returns the browser to the interrupted page
 * afterwards via the login route's `next` parameter.
 *
 * Web only: the native login flow does not yet mint sessions that can
 * satisfy a community requirement, so the event is ignored there rather than
 * sending the user through a sign-in that cannot help.
 */
export const StepUpDialog = () => {
  const { t } = useTranslation("auth");
  const { challenge, clear, open } = useAuthChallenge<StepUpEventDetail>(
    AUTH_STEP_UP_EVENT,
    (detail) => !!detail?.providerSlug,
    { listen: !Capacitor.isNativePlatform() }
  );

  // A community's listing names the ways in it counts as its own; the
  // deployment's own listing serves everything else. Both lead to the same
  // sign-in — a community does not authenticate anybody.
  const communityId = challenge?.communityId ?? 0;
  const communityProvidersQuery = useCommunityLoginProviders(communityId, {
    enabled: open && communityId > 0,
  });
  const platformProvidersQuery = useLoginProviders({ enabled: open && communityId <= 0 });
  const providerSlug = challenge?.providerSlug ?? null;
  const listing = communityId > 0 ? communityProvidersQuery.data : platformProvidersQuery.data;
  const provider = listing?.providers.find((entry) => entry.slug === providerSlug);
  const providerName = provider?.display_name ?? providerSlug ?? "";

  const beginStepUp = () => {
    if (!providerSlug) {
      return;
    }
    const loginUrl =
      provider?.login_url ?? `/api/v1/auth/${encodeURIComponent(providerSlug)}/login`;
    window.location.href = providerSignInHref(loginUrl, currentSpaPath());
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && clear()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("stepUp.title")}</DialogTitle>
          <DialogDescription>{t("stepUp.description", { providerName })}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={clear}>
            {t("stepUp.dismiss")}
          </Button>
          <Button onClick={beginStepUp}>
            <Suspense fallback={null}>
              <ProviderMark icon={provider?.icon} className="h-4 w-4" />
            </Suspense>
            {t("stepUp.continue", { providerName })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
