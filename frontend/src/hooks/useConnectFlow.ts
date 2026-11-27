import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { invalidate, q } from "@/api/query-keys";
import { connectingApp, finishConnect, openVendorPage } from "@/lib/appConnect";
import { toast } from "@/lib/mascotToast";

/**
 * A plug-in connection's vendor flow, from the Connect button to how it ended.
 *
 * `open` sends the person to the vendor's page the server built. In a browser
 * the flow ends in that tab; the desktop app waits for the window it opened
 * and finishes the flow here. `finish` finishes a flow handed back to the app,
 * which is how a phone is told (`useDeepLinks`): the outcome as a toast, and
 * the connections read again.
 */
export function useConnectFlow() {
  const { t } = useTranslation("plugins");

  const finish = useCallback(
    async (url: URL) => {
      const outcome = await finishConnect(url);
      if (!outcome) return;
      void invalidate(q.plugins(), q.pluginServices());
      const title = t(`connected.${outcome}.title`);
      // The landing page's sentence names the browser; in the app it is the
      // browser that opened, signed in as somebody else.
      const description = t(
        outcome === "sign_in_required"
          ? "connected.sign_in_required.app"
          : `connected.${outcome}.body`
      );
      if (outcome === "connected") toast.success(title, { description });
      else if (outcome === "awaiting_approval") toast.info(title, { description });
      else toast.error(title, { description });
    },
    [t]
  );

  const open = useCallback(
    async (connectUrl: string) => {
      const returned = await openVendorPage(connectUrl);
      if (returned) {
        await finish(returned);
      } else if (connectingApp() !== "desktop") {
        toast.success(t("connections.connectOpened"));
      }
    },
    [t, finish]
  );

  return { open, finish };
}
