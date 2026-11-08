import { useTranslation } from "react-i18next";

import { useReadStorageUsage } from "@/api/generated/storage/storage";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useCommunities } from "@/hooks/useCommunities";
import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { formatBytes } from "@/ui/lib/fileUtils";
import { Progress } from "@/ui/progress";

/** Percentage 0–100 of `used` against a cap, or null when the cap is
 * unlimited (null) — a null ratio renders no progress bar. */
const ratioPct = (used: number, max: number | null): number | null =>
  max && max > 0 ? Math.min(100, Math.round((used / max) * 100)) : null;

/** Community usage against its storage and member caps, and its guest cap.
 *
 * On the seat's Usage tab, the first in community settings, on every install:
 * self-hosted, the caps are the operator's; hosted, they come with the plan,
 * which `CommunityBillingPanel` shows below it. The numbers are the administration
 * half of `CommunityRead`, which the API sends to admins alone — as does the
 * storage-usage endpoint below. */
export const CommunityUsagePanel = () => {
  const { t } = useTranslation(["communities", "common"]);
  const { activeCommunity } = useCommunities();
  // The tab is "Usage" alone unless the plan sits beside this card.
  const { billing, guestsEnabled } = useAppConfig();

  const communityId = activeCommunity?.id;
  // Read on the settings surface, by the same rung as the caps beside it, so a
  // settings grant reaches it too. Until it answers — or if it cannot — the
  // figure is not shown at all: an empty bar would read as nothing stored.
  const { data: usage, isError } = useReadStorageUsage(communityId ?? 0, {
    query: { enabled: communityId != null },
  });

  if (!activeCommunity) {
    return null;
  }

  const usedBytes = usage?.usage_bytes;
  const maxBytes = activeCommunity.max_storage_bytes; // null = unlimited
  const members = activeCommunity.member_count;
  const maxUsers = activeCommunity.max_users; // null = unlimited
  const storagePct = usedBytes == null ? null : ratioPct(usedBytes, maxBytes);
  const memberPct = ratioPct(members, maxUsers);
  const maxGuests = activeCommunity.max_guests; // null = unlimited, 0 = none
  // A community that cannot have guests hears nothing about them.
  const showGuests = guestsEnabled && maxGuests !== 0;

  return (
    <Card>
      {billing ? (
        <CardHeader>
          <CardTitle>{t("usagePanel.title")}</CardTitle>
        </CardHeader>
      ) : null}
      <CardContent className={billing ? "space-y-6" : "space-y-6 pt-6"}>
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="font-medium">{t("usagePanel.storage")}</span>
            <span className="text-muted-foreground">
              {usedBytes == null
                ? isError
                  ? t("usagePanel.storageUnavailable")
                  : null
                : maxBytes == null
                  ? t("usagePanel.usedOfUnlimited", { used: formatBytes(usedBytes) })
                  : t("usagePanel.usedOfMax", {
                      used: formatBytes(usedBytes),
                      max: formatBytes(maxBytes),
                    })}
            </span>
          </div>
          {storagePct != null && <Progress value={storagePct} />}
        </div>

        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="font-medium">{t("usagePanel.members")}</span>
            <span className="text-muted-foreground">
              {maxUsers == null
                ? t("usagePanel.membersOfUnlimited", { used: members })
                : t("usagePanel.membersOfMax", { used: members, max: maxUsers })}
            </span>
          </div>
          {memberPct != null && <Progress value={memberPct} />}
        </div>

        {showGuests && (
          <div className="flex justify-between text-sm">
            <span className="font-medium">{t("usagePanel.guests")}</span>
            <span className="text-muted-foreground">
              {maxGuests == null
                ? t("usagePanel.guestsUnlimited")
                : t("usagePanel.guestsUpTo", { max: maxGuests })}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
