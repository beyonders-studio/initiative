/**
 * What the front door's three pages need to know about the deployment they
 * are on, asked once and shared: whether somebody may make an account here,
 * and whether plans may be shown at all.
 *
 * Plans show only where a billing portal is configured and this device may
 * sell: always on the web and the desktop app, and in a phone app only where
 * its store allows a link to a web purchase (`@/lib/storeSelling`).
 */

import { useBootstrapStatus } from "@/api/generated/auth/auth";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useBillingCatalog } from "@/hooks/useBillingCatalog";
import { useStoreSellingAnswer } from "@/lib/storeSelling";

export const useFrontDoor = () => {
  const appConfig = useAppConfig();
  const { billing } = appConfig;

  const bootstrap = useBootstrapStatus({ query: { staleTime: 60_000 } });
  // Until the server answers, the page offers sign-up: most deployments allow
  // it, and the button leaving is better than the button arriving late.
  const registrationOpen = bootstrap.data?.public_registration_enabled !== false;

  const sellsHere = useStoreSellingAnswer();
  const sellsPlans = billing != null && sellsHere === true;
  const catalog = useBillingCatalog(sellsPlans ? billing?.url : undefined);
  // The header offers Pricing only once there is a price book to show.
  const showsPricing = sellsPlans && catalog.data != null && !catalog.isError;

  // Still loading while a phone's store has not said whether it may sell.
  const isLoading = appConfig.isLoading || sellsHere === undefined;

  return { ...appConfig, isLoading, registrationOpen, sellsPlans, catalog, showsPricing };
};
