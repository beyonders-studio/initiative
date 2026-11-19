import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { useServer } from "@/hooks/useServer";
import { toast } from "@/lib/mascotToast";

/**
 * Copies a link to one of the app's routes, on the server the app is signed in
 * to rather than wherever the app itself is served from, so it opens the same
 * page in a browser or another app. Says whether it worked.
 */
export const useCopyLink = () => {
  const { t } = useTranslation("common");
  const { getServerOrigin } = useServer();

  return useCallback(
    async (path: string) => {
      const origin = getServerOrigin() ?? window.location.origin;
      try {
        await navigator.clipboard.writeText(new URL(path, origin).toString());
        toast.success(t("pageLinkCopied"));
      } catch {
        toast.error(t("pageLinkCopyFailed"));
      }
    },
    [getServerOrigin, t]
  );
};
