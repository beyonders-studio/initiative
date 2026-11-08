import { Clock, Lock } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useCommunities } from "@/hooks/useCommunities";
import { minutesLeft } from "@/ui/lib/formatDate";

/**
 * Banner shown across community pages when the active community is reached via a
 * time-bound PAM access grant (not real membership) — access is temporary
 * and, for read grants, read-only — OR when the community's content is frozen
 * (read_only lifecycle status), so members know why write affordances are
 * gone before they try one.
 */
export const CommunityAccessBanner = () => {
  const { t } = useTranslation("communities");
  const { activeCommunity, activeCommunityReadOnly } = useCommunities();

  if (activeCommunity?.accessType !== "grant") {
    // Real membership in a frozen community: writes are disabled server-side, so
    // say so plainly. The banner discloses the effect, not the reason — the
    // lifecycle status itself only reaches community admins (settings page).
    if (activeCommunity?.content_read_only) {
      // A Lock icon, not the Clock the PAM-grant banner uses below: a frozen
      // community is read-only, not time-limited, so it must not read as "your
      // access expires soon".
      return (
        <div className="flex items-center gap-2 border-amber-500/30 border-b bg-amber-500/10 px-4 py-2 text-amber-700 text-sm dark:text-amber-300">
          <Lock className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{t("readOnlyBanner.message", { community: activeCommunity.name })}</span>
        </div>
      );
    }
    return null;
  }

  const left = minutesLeft(activeCommunity.grantExpiresAt);
  const message = activeCommunityReadOnly
    ? t("grantBanner.readOnly", { community: activeCommunity.name })
    : t("grantBanner.readWrite", { community: activeCommunity.name });
  // Operational context for the operator: this community is under a moderation hold.
  const statusNote =
    activeCommunity.status === "suspended"
      ? t("grantBanner.communitySuspended")
      : activeCommunity.status === "on_hold"
        ? t("grantBanner.communityOnHold")
        : activeCommunity.status === "read_only"
          ? t("grantBanner.communityReadOnly")
          : null;

  return (
    <div className="flex items-center gap-2 border-amber-500/30 border-b bg-amber-500/10 px-4 py-2 text-amber-700 text-sm dark:text-amber-300">
      <Clock className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span>
        {message}
        {statusNote !== null ? ` · ${statusNote}` : ""}
        {left !== null ? ` · ${t("expiresInMinutes", { minutes: left })}` : ""}
      </span>
    </div>
  );
};
