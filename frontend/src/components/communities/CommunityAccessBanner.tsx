import { Clock, Lock } from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { useCommunities } from "@/hooks/useCommunities";
import { formatDateTime, minutesLeft } from "@/ui/lib/formatDate";

/** The longest a browser timer waits; a later end is picked up on a later read. */
const MAX_TIMER_MS = 2_147_483_647;

/**
 * Banner shown across community pages when the active community is reached via a
 * time-bound PAM access grant (not real membership) — access is temporary
 * and, for read grants, read-only — OR when the community's content is frozen
 * (read_only lifecycle status), so members know why write affordances are
 * gone before they try one.
 */
export const CommunityAccessBanner = () => {
  const { t } = useTranslation("communities");
  const { activeCommunity, activeCommunityReadOnly, refreshCommunities } = useCommunities();
  const timedOutUntil = activeCommunity?.timed_out_until ?? null;

  // A timeout ends by itself. Re-read the community then, so the write
  // controls come back without a reload.
  useEffect(() => {
    if (!timedOutUntil) return;
    const wait = new Date(timedOutUntil).getTime() - Date.now();
    if (wait > MAX_TIMER_MS) return;
    const timer = setTimeout(() => void refreshCommunities(), Math.max(0, wait) + 1000);
    return () => clearTimeout(timer);
  }, [timedOutUntil, refreshCommunities]);

  if (activeCommunity?.accessType !== "grant") {
    // Timed out here: they read, and change nothing, until it ends.
    if (timedOutUntil) {
      return (
        <div className="flex items-center gap-2 border-amber-500/30 border-b bg-amber-500/10 px-4 py-2 text-amber-700 text-sm dark:text-amber-300">
          <Clock className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>
            {t("timeOut.banner", {
              community: activeCommunity?.name,
              time: formatDateTime(timedOutUntil),
            })}
          </span>
        </div>
      );
    }
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
