import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";

import { PixelSparkle } from "@/components/effects/svg/PixelSparkle";
import { ContinueButton, SkipButton } from "@/components/start/stepParts";
import type { CatalogTier } from "@/hooks/useBillingCatalog";
import { cn } from "@/ui/lib/utils";

/** The catalog's plans as cards, the entry plan picked until another is. */
export const PlanStep = ({
  tiers,
  entry,
  chosen,
  loading,
  onPick,
  onContinue,
  onSkip,
  disabled,
}: {
  tiers: CatalogTier[];
  entry: CatalogTier | undefined;
  chosen: CatalogTier | undefined;
  loading: boolean;
  onPick: (tierId: string) => void;
  onContinue: () => void;
  onSkip: () => void;
  disabled?: boolean;
}) => {
  const { t } = useTranslation("auth");
  return (
    <>
      {loading ? <p className="text-muted-foreground text-sm">{t("start.plan.loading")}</p> : null}
      <div className="grid gap-3">
        {tiers.map((tier) => {
          const picked = tier === chosen;
          return (
            <button
              key={tier.id}
              type="button"
              aria-pressed={picked}
              onClick={() => onPick(tier.id)}
              className={cn(
                "flex items-start gap-3 rounded-xl border-2 bg-card p-3 text-left transition-colors hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                picked && "border-primary bg-primary/5"
              )}
            >
              <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-muted">
                <PixelSparkle size={24} color={tier === entry ? "#34D399" : "#FBBF24"} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-baseline justify-between gap-2">
                  <span className="font-semibold">{tier.name}</span>
                  <span className="font-semibold">{tier.price.display}</span>
                </span>
                {tier.tagline ? (
                  <span className="mt-1 block text-muted-foreground text-sm">{tier.tagline}</span>
                ) : null}
              </span>
              <Check
                aria-hidden="true"
                className={cn("mt-0.5 h-4 w-4 shrink-0 text-primary", !picked && "invisible")}
              />
            </button>
          );
        })}
      </div>
      <ContinueButton onClick={onContinue} disabled={disabled} />
      <SkipButton onClick={onSkip} disabled={disabled} />
    </>
  );
};
