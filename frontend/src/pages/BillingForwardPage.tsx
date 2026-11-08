import { Browser } from "@capacitor/browser";
import { Capacitor } from "@capacitor/core";
import { useParams, useSearch } from "@tanstack/react-router";
import { CreditCard, Loader2, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { type BillingPortalPage, useBillingPortal } from "@/hooks/useBillingPortal";
import { getErrorMessage } from "@/lib/errorMessage";
import { useStoreSellingAnswer } from "@/lib/storeSelling";
import { StatusMessage } from "@/ui/status-message";

/**
 * `/c/$communityId/billing?page=…`: mints a portal handoff for the community and
 * replaces this tab with the portal, so Back does not land here again.
 *
 * A phone app opens the portal in the system browser sheet instead, where its
 * store allows a link to a web purchase (`@/lib/storeSelling`). Where it does
 * not, the page goes nowhere and says only that plans are not changed in the
 * app: it names no browser, portal or link.
 */
export const BillingForwardPage = () => {
  const { t } = useTranslation("communities");
  const { communityId } = useParams({ strict: false }) as { communityId?: string };
  const { page } = useSearch({ strict: false }) as { page?: BillingPortalPage };
  const sellsHere = useStoreSellingAnswer();
  const { billing, isLoading, portalUrl } = useBillingPortal();
  const [error, setError] = useState<string | null>(null);
  const [opened, setOpened] = useState(false);
  // Once per visit, StrictMode's second effect included: each request mints a token.
  const started = useRef(false);

  const id = Number(communityId);
  const target: BillingPortalPage = page === "upgrade" ? "upgrade" : "manage";

  useEffect(() => {
    if (started.current || sellsHere !== true || isLoading || !billing) return;
    started.current = true;
    if (!Number.isInteger(id) || id <= 0) {
      setError(t("billingForward.error"));
      return;
    }
    portalUrl(id, target)
      .then(async (url) => {
        if (!url) return;
        const platform = Capacitor.getPlatform();
        if (platform !== "ios" && platform !== "android") {
          window.location.replace(url);
          return;
        }
        // The phone apps open the portal in the browser sheet and stay here.
        await Browser.open({ url });
        setOpened(true);
      })
      .catch((err: unknown) => setError(getErrorMessage(err, "communities:billingForward.error")));
  }, [billing, id, isLoading, sellsHere, portalUrl, t, target]);

  const message = (icon: React.ReactNode, title: string, description: string) => (
    <div className="flex min-h-app items-center justify-center">
      <StatusMessage
        icon={icon}
        title={title}
        description={description}
        backTo="/"
        backLabel={t("notMember.backToHome")}
      />
    </div>
  );

  if (sellsHere === false) {
    return message(
      <CreditCard />,
      t("billingForward.nativeTitle"),
      t("billingForward.nativeDescription")
    );
  }
  if (!isLoading && !billing) {
    return message(
      <CreditCard />,
      t("billingForward.notConfiguredTitle"),
      t("billingForward.notConfiguredDescription")
    );
  }
  if (error) {
    return message(<ShieldAlert />, t("billingForward.errorTitle"), error);
  }
  if (opened) {
    return message(
      <CreditCard />,
      t("billingForward.openedTitle"),
      t("billingForward.openedDescription")
    );
  }
  return (
    <div className="flex min-h-app flex-col items-center justify-center gap-3 px-6 text-center">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      <p className="text-muted-foreground text-sm">{t("billingForward.opening")}</p>
    </div>
  );
};
