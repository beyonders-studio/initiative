import { ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  PluginAvailability,
  type PluginServiceRegistrationRead,
} from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/ui/badge";
import { formatDate } from "@/ui/lib/formatDate";

/**
 * A plug-in service's state and reach, as tags: whether it is live, whatever
 * stops it, who it reaches, and where it comes from. Beta and operations-only
 * are coloured, the latter in the platform's own accent, so either reads at a
 * glance in a long list. Verified is a listing the registry signed, checked
 * against the key this server trusts; built by Initiative is one this project
 * publishes.
 */
export const PluginServiceBadges = ({
  registration,
}: {
  registration: PluginServiceRegistrationRead;
}) => {
  const { t } = useTranslation("settings");
  return (
    <div className="flex flex-wrap items-center gap-2">
      {registration.live ? (
        <Badge variant="outline" className="border-transparent bg-emerald-600 text-white">
          {t("pluginServices.liveBadge")}
        </Badge>
      ) : (
        <Badge variant="outline" className="border-dashed text-muted-foreground">
          {t("pluginServices.notLiveBadge")}
        </Badge>
      )}
      {registration.suspended_at != null && (
        <Badge variant="outline" className="border-destructive text-destructive">
          {t("pluginServices.suspendedBadge", { date: formatDate(registration.suspended_at) })}
        </Badge>
      )}
      {!registration.publisher_enabled && (
        <Badge variant="outline" className="border-destructive text-destructive">
          {t("pluginServices.publisherDisabledBadge")}
        </Badge>
      )}
      {registration.availability === PluginAvailability.beta && (
        <Badge variant="warning">{t("pluginServices.betaBadge")}</Badge>
      )}
      {registration.availability === PluginAvailability.operations ? (
        <Badge>
          {t(
            registration.mandatory
              ? "pluginServices.operationsMandatoryBadge"
              : "pluginServices.operationsOnlyBadge"
          )}
        </Badge>
      ) : (
        registration.mandatory && (
          <Badge variant="secondary">{t("pluginServices.mandatoryBadge")}</Badge>
        )
      )}
      {registration.source === "registry" && (
        <Badge
          variant="outline"
          className="gap-1 border-sky-600/60 text-sky-700 dark:text-sky-300"
          title={t("pluginServices.verifiedHelp")}
        >
          <ShieldCheck className="size-3.5" aria-hidden="true" />
          {t("pluginServices.verifiedBadge")}
        </Badge>
      )}
      {registration.first_party && (
        <Badge variant="secondary">{t("pluginServices.firstPartyBadge")}</Badge>
      )}
    </div>
  );
};
