/**
 * How a provider placement rule reads, wherever one is listed: the operator's
 * placement page, and a community's own Security page, which shows the rules
 * the deployment wrote for it.
 *
 * A rule matches a group, a directory (a claim and its value), or a group
 * within a directory. It is written once here so both pages say it the same
 * way.
 */

import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import type { ProviderPlacementRuleRead } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

type RuleMatch = Pick<ProviderPlacementRuleRead, "claim_value" | "scope_claim" | "scope_value">;

/** What a rule matches, in one line. */
export const describePlacementMatch = (rule: RuleMatch, t: TFunction<"settings">): string => {
  const hasDirectory = Boolean(rule.scope_claim && rule.scope_value);
  if (rule.claim_value && hasDirectory) {
    return t("providerPlacement.match.groupInDirectory", {
      group: rule.claim_value,
      claim: rule.scope_claim,
      value: rule.scope_value,
    });
  }
  if (rule.claim_value) {
    return t("providerPlacement.match.group", { group: rule.claim_value });
  }
  return t("providerPlacement.match.directory", {
    claim: rule.scope_claim ?? "",
    value: rule.scope_value ?? "",
  });
};

/** The two standings a rule may hand out, spelled out rather than
 *  interpolated into the key. */
export const placementRoleLabel = (role: string, t: TFunction<"settings">): string =>
  role === "admin" ? t("communityAuth.rules.role.admin") : t("communityAuth.rules.role.member");

/** Marks a rule that places nobody right now, with the reason on hover or
 *  focus. */
export const NotApplyingBadge = () => {
  const { t } = useTranslation("settings");
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          {/* Focusable so the reason is reachable from the keyboard too. */}
          <span
            // biome-ignore lint/a11y/noNoninteractiveTabindex: the tooltip trigger needs focus
            tabIndex={0}
            className="rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Badge variant="outline">{t("providerPlacement.notApplying")}</Badge>
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs">
          {t("providerPlacement.notApplyingHint")}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};
