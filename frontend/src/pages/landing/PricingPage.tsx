/**
 * Plans, as the billing portal describes them.
 *
 * Only on a deployment with a billing portal, on a device that may sell;
 * anywhere else the address goes back to the front page. The plans themselves
 * are the portal's grid, framed (`PricingGridFrame`): the same cards in the
 * same steps as the portal's own pricing page, in the reader's language and
 * currency. This page reads the catalog only for its headline, and to know
 * there is a price book to show.
 */

import { Link, Navigate } from "@tanstack/react-router";
import type { LucideIcon } from "lucide-react";
import { ArrowUpRight, Code2, Layers, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";

import { portalPricingUrl } from "@/hooks/useBillingCatalog";
import { Button } from "@/ui/button";

import { DarkBand } from "./DarkBand";
import { LandingShell } from "./LandingShell";
import { PricingGridFrame } from "./PricingGridFrame";
import { useFrontDoor } from "./useFrontDoor";
import { usePageMeta } from "./usePageMeta";

const Fact = ({ icon: Icon, title, body }: { icon: LucideIcon; title: string; body: string }) => (
  <li className="flex items-start gap-3.5 rounded-2xl bg-muted/60 p-5">
    <Icon className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
    <div>
      <h3 className="font-bold">{title}</h3>
      <p className="mt-0.5 text-muted-foreground text-sm">{body}</p>
    </div>
  </li>
);

export const PricingPage = () => {
  const { t } = useTranslation("landing");
  const { billing, isLoading, sellsPlans, catalog, registrationOpen } = useFrontDoor();
  usePageMeta(t("meta.pricingTitle"), catalog.data?.subhead ?? t("meta.pricingDescription"));

  // Nothing to sell here (no portal, or a device that may not): the front page instead.
  if (!isLoading && !sellsPlans) {
    return <Navigate to="/welcome" replace />;
  }

  const portalUrl = billing?.url ?? "";

  return (
    <LandingShell current="pricing">
      <DarkBand stars aria-labelledby="landing-pricing-title">
        <div className="relative mx-auto max-w-6xl px-4 pt-10 pb-24 sm:px-8 sm:pt-18 sm:pb-28">
          <h1
            id="landing-pricing-title"
            className="font-extrabold text-[2.6rem] leading-tight tracking-tight sm:text-6xl"
          >
            {catalog.data?.headline ?? t("pricing.sectionLabel")}
          </h1>
          {catalog.data?.subhead ? (
            <p className="mt-4 max-w-3xl text-lg text-slate-300">{catalog.data.subhead}</p>
          ) : null}
        </div>
      </DarkBand>

      <div className="mx-auto max-w-6xl px-4 sm:px-8">
        {catalog.isError ? (
          <div
            className="relative -mt-12 rounded-3xl border bg-card p-8 text-center shadow-xl"
            role="status"
          >
            <h2 className="font-bold text-xl">{t("pricing.unavailableTitle")}</h2>
            <p className="mt-2 text-muted-foreground">{t("pricing.unavailableBody")}</p>
            <Button variant="outline" className="mt-5" asChild>
              <Link to="/welcome">{t("pricing.back")}</Link>
            </Button>
          </div>
        ) : catalog.data && portalUrl ? (
          <div className="relative -mt-12">
            <PricingGridFrame portalUrl={portalUrl} registrationOpen={registrationOpen} />
          </div>
        ) : (
          <p
            className="relative -mt-8 text-center text-muted-foreground text-sm"
            aria-live="polite"
          >
            {t("pricing.loading")}
          </p>
        )}

        <ul
          className="mt-12 grid gap-3 sm:gap-4 md:grid-cols-3"
          aria-label={t("pricing.everyPlanAria")}
        >
          <Fact icon={Layers} title={t("pricing.sameTitle")} body={t("pricing.sameBody")} />
          <Fact icon={Code2} title={t("pricing.openTitle")} body={t("pricing.openBody")} />
          <Fact icon={ShieldCheck} title={t("pricing.dataTitle")} body={t("pricing.dataBody")} />
        </ul>
        {portalUrl ? (
          <p className="mt-8 mb-20 text-center sm:mb-24">
            <a
              href={portalPricingUrl(portalUrl)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 font-semibold text-primary hover:underline"
            >
              {t("pricing.seeAll")}
              <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
            </a>
          </p>
        ) : null}
      </div>
    </LandingShell>
  );
};
