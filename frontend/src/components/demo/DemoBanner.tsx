import { Link } from "@tanstack/react-router";
import { Hourglass } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { type DemoCopy, useDemoCopy } from "@/hooks/useDemoCopy";
import { useLiveClockValue } from "@/hooks/useRelativeTime";
import { listFormat, numberFormat } from "@/lib/intl";

const hours = numberFormat(undefined, { style: "unit", unit: "hour", unitDisplay: "narrow" });
const minutes = numberFormat(undefined, { style: "unit", unit: "minute", unitDisplay: "narrow" });
const parts = listFormat(undefined, { type: "unit", style: "narrow" });

/** Whole hours and minutes until `expiresAt`, as "3h 12m", never below none. */
const timeLeft = (expiresAt: number, now: number): string => {
  const left = Math.max(0, Math.ceil((expiresAt - now) / 60_000));
  const whole = Math.floor(left / 60);
  const rest = minutes.format(left % 60);
  return whole > 0 ? parts.format([hours.format(whole), rest]) : rest;
};

/**
 * A demo visitor's copy, and how long it has left, in the row the recents tabs
 * use for everyone else.
 */
export const DemoBanner = ({ copy }: { copy: DemoCopy }) => {
  const { t } = useTranslation("auth");
  const expiresAt = new Date(copy.expiresAt).getTime();
  const remaining = useLiveClockValue((now) => timeLeft(expiresAt, now));

  return (
    <div className="flex min-h-12 items-center gap-3 border-b px-4 py-2 text-sm md:border-b-0">
      <Hourglass className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
      <p className="min-w-0 flex-1">
        {t("demo.banner.message", { community: copy.community?.name ?? "", remaining })}
      </p>
      <div className="flex shrink-0 items-center gap-3">
        <Link to="/welcome" className="text-primary underline-offset-4 hover:underline">
          {t("demo.banner.mainSite")}
        </Link>
      </div>
    </div>
  );
};

/**
 * The first row of the app's top bar: a demo visitor's banner, or `children`
 * (the recents tabs) for every other account.
 */
export const DemoBannerOrTabs = ({ children }: { children: ReactNode }) => {
  const copy = useDemoCopy();
  return copy ? <DemoBanner copy={copy} /> : children;
};
