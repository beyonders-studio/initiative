import { Capacitor } from "@capacitor/core";
import { useEffect, useRef, useState } from "react";

import { getVersion } from "@/api/generated/version/version";
import { compareVersions } from "@/hooks/useLatestVersion";
import { setPendingUpdate } from "@/lib/pendingUpdate";
import { getItem, setItem } from "@/lib/storage";

const CHECK_INTERVAL = 5 * 60 * 1000; // 5 minutes
const CURRENT_VERSION = __APP_VERSION__;
const DISMISSED_VERSION_KEY = "initiative-dismissed-version";

/**
 * Tell a web reader that the server runs a newer version than the page.
 *
 * Off in the native app: there the update arrives as a bundle, and
 * `useNativeUpdate` offers it with a reload button that installs it. Two
 * prompts for one release would stack, and this one's reload would not.
 */
export const useVersionCheck = () => {
  const hasShownNotification = useRef(false);
  const [updateAvailable, setUpdateAvailable] = useState<{
    show: boolean;
    version: string;
  }>({ show: false, version: "" });

  useEffect(() => {
    if (Capacitor.isNativePlatform()) {
      return;
    }

    const checkVersion = async () => {
      try {
        const result = await getVersion();
        const serverVersion = result.version;

        // Only show update popup if server version is newer than client version
        const isServerNewer = compareVersions(serverVersion, CURRENT_VERSION) > 0;
        if (!isServerNewer) {
          return;
        }
        // The Update button offers the reload whether or not the prompt was closed.
        setPendingUpdate({ action: "reload", run: () => window.location.reload() });

        // Check if user already dismissed this specific version
        const dismissedVersion = getItem(DISMISSED_VERSION_KEY);
        if (dismissedVersion === serverVersion) {
          return;
        }

        if (!hasShownNotification.current) {
          hasShownNotification.current = true;
          setUpdateAvailable({ show: true, version: serverVersion });
        }
      } catch (error) {
        // Silently fail - version check is not critical
        console.debug("Version check failed:", error);
      }
    };

    // Check immediately on mount
    void checkVersion();

    // Then check periodically
    const interval = setInterval(() => {
      void checkVersion();
    }, CHECK_INTERVAL);

    return () => clearInterval(interval);
  }, []);

  const closeDialog = () => {
    // Persist the dismissed version so it doesn't reappear on refresh
    if (updateAvailable.version) {
      setItem(DISMISSED_VERSION_KEY, updateAvailable.version);
    }
    setUpdateAvailable({ show: false, version: "" });
  };

  return { updateAvailable, closeDialog };
};
