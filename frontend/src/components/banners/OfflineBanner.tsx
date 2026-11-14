import { CloudOff } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useAuth } from "@/hooks/useAuth";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { isOfflineCacheEnabled, offlineCacheSyncedAt } from "@/lib/offlineCache";
import { formatDateTime } from "@/ui/lib/formatDate";

/**
 * Says, plainly, that what is on screen came off this device rather than from
 * the server, so a list is never mistaken for a current one.
 *
 * The timestamp is the last moment this device wrote its cache — that is, the
 * last time it was online — which is the honest answer to "how old is this?".
 */
export const OfflineBanner = () => {
  const { t } = useTranslation("common");
  const { isOnline } = useNetworkStatus();
  const { sessionUnverified } = useAuth();

  if (!isOfflineCacheEnabled()) return null;
  if (isOnline && !sessionUnverified) return null;

  const syncedAt = offlineCacheSyncedAt();

  return (
    <div
      className="flex items-center gap-2 border-slate-500/30 border-b bg-slate-500/10 px-4 py-2 text-slate-700 text-sm dark:text-slate-300"
      role="status"
    >
      <CloudOff className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span>
        {t("offline.banner")}
        {syncedAt !== null
          ? ` · ${t("offline.lastUpdated", { when: formatDateTime(new Date(syncedAt).toISOString()) })}`
          : ""}
      </span>
    </div>
  );
};
