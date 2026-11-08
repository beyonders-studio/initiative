import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { compareVersions, useLatestVersion } from "@/hooks/useLatestVersion";
import { toast } from "@/lib/mascotToast";
import { getItem, setItem } from "@/lib/storage";

import { VersionDialog } from "./VersionDialog";

const CURRENT_VERSION = __APP_VERSION__;
const LAST_RUN_VERSION_KEY = "initiative-last-run-version";

/**
 * Whether the app has just moved to a newer version since it last ran here,
 * recording the current one either way. A first run records it and says
 * nothing: there is no "before" to compare with.
 */
export const takeVersionChange = (current: string = CURRENT_VERSION): boolean => {
  const previous = getItem(LAST_RUN_VERSION_KEY);
  if (previous !== current) {
    setItem(LAST_RUN_VERSION_KEY, current);
  }
  return previous !== null && compareVersions(current, previous) > 0;
};

/**
 * "Updated to version X" — a toast once the app runs a newer version than it
 * last did, whose "What's new" opens the version dialog.
 */
export const UpdatedNotice = () => {
  const { t } = useTranslation("common");
  const [dialogOpen, setDialogOpen] = useState(false);
  const { data: latestVersion, isLoading } = useLatestVersion();

  useEffect(() => {
    if (!takeVersionChange()) {
      return;
    }
    toast.success(t("appUpdate.updated", { version: CURRENT_VERSION }), {
      action: { label: t("appUpdate.whatsNew"), onClick: () => setDialogOpen(true) },
    });
  }, [t]);

  return (
    <VersionDialog
      open={dialogOpen}
      onOpenChange={setDialogOpen}
      currentVersion={CURRENT_VERSION}
      latestVersion={latestVersion}
      hasUpdate={latestVersion ? compareVersions(latestVersion, CURRENT_VERSION) > 0 : false}
      isLoadingVersion={isLoading}
    />
  );
};
