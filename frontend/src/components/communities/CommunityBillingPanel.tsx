import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import type {
  CommunityBillingChargeRead,
  CommunityBillingSummaryRead,
} from "@/api/generated/initiativeAPI.schemas";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import { useCommunities } from "@/hooks/useCommunities";
import { useCommunityBillingSummary } from "@/hooks/useCommunityBillingSummary";
import { holdsBillingSeat, trialDaysLeft } from "@/lib/billingSummary";
import { parseDateValue } from "@/lib/formatDate";
import { Badge, type BadgeProps } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { dateTimeFormat, numberFormat } from "@/ui/lib/intl";
import { Separator } from "@/ui/separator";

/** A charge in minor units as the currency writes it, or null when the
 *  browser does not know the currency. */
const formatCharge = (charge: CommunityBillingChargeRead, lang: string): string | null => {
  try {
    const format = numberFormat(lang, { style: "currency", currency: charge.currency });
    const digits = format.resolvedOptions().maximumFractionDigits ?? 2;
    return format.format(charge.total / 10 ** digits);
  } catch {
    return null;
  }
};

interface PlanStatus {
  badge?: string;
  variant: BadgeProps["variant"];
  detail?: string;
}

/** What the badge says, by what matters most to the seat right now: a charge
 *  that failed, then a plan about to stop, then a trial, then a renewal.
 *  Where nothing may be sold (`canSell` false) it states the
 *  facts without asking anyone to pay, and names no amount. */
const planStatus = (
  summary: CommunityBillingSummaryRead,
  t: TFunction<["communities", "common"]>,
  lang: string,
  canSell: boolean
): PlanStatus | null => {
  const formatDay = (value: string | null | undefined): string | null => {
    const date = parseDateValue(value);
    return date ? dateTimeFormat(lang, { dateStyle: "long" }).format(date) : null;
  };

  if (summary.payment_failed) {
    return {
      badge: t("billingPanel.status.paymentFailed"),
      variant: "destructive",
      detail: canSell
        ? t("billingPanel.status.paymentFailedDetail")
        : t("billingPanel.status.paymentFailedDetailInApp"),
    };
  }

  const change = summary.scheduled_change;
  const changeOn = formatDay(change?.on);
  if (change && changeOn) {
    if (change.action === "cancel") {
      return {
        variant: "warning",
        detail: t("billingPanel.status.endsDetail", { date: changeOn }),
      };
    }
    if (change.action === "pause") {
      return {
        badge: t("billingPanel.status.pauses", { date: changeOn }),
        variant: "secondary",
      };
    }
    return {
      badge: t("billingPanel.status.resumes", { date: changeOn }),
      variant: "secondary",
    };
  }

  const days = trialDaysLeft(summary);
  const trialEndsOn = formatDay(summary.trial_ends_on);
  if (days != null && trialEndsOn) {
    // The same words in the phone app: Paddle bills the plan when its trial
    // ends, which is a fact to state rather than anything to buy.
    return {
      variant: "secondary",
      detail: t("billingPanel.status.trialDetail", { date: trialEndsOn }),
    };
  }

  const renewsOn = formatDay(summary.renews_on);
  if (renewsOn) {
    const amount = canSell && summary.next_charge ? formatCharge(summary.next_charge, lang) : null;
    return {
      badge: amount
        ? t("billingPanel.status.renewsWithAmount", { date: renewsOn, amount })
        : t("billingPanel.status.renews", { date: renewsOn }),
      variant: "secondary",
    };
  }

  return null;
};

/** The community's plan, as the billing service tells it right now.
 *
 * The seat's alone, and only where the deployment has a billing portal: it
 * sits under the usage bars on the seat-only Usage tab, which a self-hosted
 * install shows without it. A grantee lent the seat — support — sees the bars
 * and never this (`holdsBillingSeat`). Nothing here changes billing — every action hands
 * off to the billing portal, and the summary is fetched per view and kept
 * nowhere. Where nothing may be sold (`canSell` false) it shows the plan with no
 * actions at all. */
export const CommunityBillingPanel = () => {
  const { t, i18n } = useTranslation(["communities", "common"]);
  const lang = i18n.resolvedLanguage ?? i18n.language;
  const { activeCommunity } = useCommunities();
  const { billing, canSell, openPortal } = useBillingPortal();

  const { data: summary, isError } = useCommunityBillingSummary(activeCommunity);

  if (!activeCommunity || !billing || !holdsBillingSeat(activeCommunity)) {
    return null;
  }

  const unavailable = isError || (summary != null && !summary.available);
  const status = summary?.available ? planStatus(summary, t, lang, canSell) : null;
  // Billing says whether there is a plan above this one, and a subscription
  // the portal can cancel: neither on the top plan, nor cancel on a free one.
  const canUpgrade = Boolean(summary?.available && summary.can_upgrade);
  const canCancel = Boolean(summary?.available && summary.can_cancel);
  const tierLabel =
    (summary?.available ? summary.tier_name : null) ??
    activeCommunity.tier_name ??
    t("usagePanel.selfHosted");

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("billingPanel.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm">
              <span className="text-muted-foreground">{t("usagePanel.currentPlan")} </span>
              <span className="font-semibold">{tierLabel}</span>
            </p>
            {status?.badge && <Badge variant={status.variant}>{status.badge}</Badge>}
          </div>
          {status?.detail && <p className="text-muted-foreground text-sm">{status.detail}</p>}
          {unavailable && (
            <p className="text-muted-foreground text-sm">{t("billingPanel.unavailable")}</p>
          )}
        </div>

        {canSell ? (
          <>
            <div className="flex flex-wrap gap-2">
              {summary?.payment_failed ? (
                <Button size="sm" onClick={() => void openPortal(activeCommunity.id, "manage")}>
                  {t("billingPanel.updatePaymentMethod")}
                </Button>
              ) : (
                <>
                  {canUpgrade && (
                    <Button
                      size="sm"
                      onClick={() => void openPortal(activeCommunity.id, "upgrade")}
                    >
                      {t("usagePanel.upgrade")}
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant={canUpgrade ? "outline" : "default"}
                    onClick={() => void openPortal(activeCommunity.id, "manage")}
                  >
                    {t("usagePanel.manageBilling")}
                  </Button>
                </>
              )}
            </div>
            <p className="text-muted-foreground text-sm">{t("billingPanel.changeInPortal")}</p>

            {canCancel && (
              <>
                <Separator />
                <p className="text-muted-foreground text-sm">{t("billingPanel.cancelAnytime")}</p>
              </>
            )}
          </>
        ) : (
          <p className="text-muted-foreground text-sm">{t("billingPanel.notInApp")}</p>
        )}
      </CardContent>
    </Card>
  );
};
