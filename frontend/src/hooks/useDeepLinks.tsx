import { App, type URLOpenListenerEvent } from "@capacitor/app";
import { Browser } from "@capacitor/browser";
import { useRouter } from "@tanstack/react-router";
import { useEffect } from "react";

import { useAuth } from "@/hooks/useAuth";
import { redeemNativeSignIn, takePendingSignIn } from "@/lib/nativeSignIn";
import { takeBrowserAnswer } from "@/lib/passkeys";

import { useServer } from "./useServer";

/** Whether `url` is the address the app's sign-in comes back to. */
const isSignInCallback = (url: URL) =>
  url.protocol === "initiative:" && url.host === "oidc" && url.pathname === "/callback";

/**
 * Take the links the system browser hands back to the app: a passkey prompt's
 * answer, and a sign-in the app began there.
 *
 * Handles the link whether it wakes the running app or starts it: the phone
 * often closes the app while the browser is in front. Only a callback for a
 * sign-in this app began, against the server it is on, is answered.
 */
export function useDeepLinks() {
  const router = useRouter();
  const { isNativePlatform, getServerOrigin } = useServer();
  const { completeOidcLogin, applySignIn } = useAuth();

  useEffect(() => {
    if (!isNativePlatform) return;

    const handle = async (raw: string) => {
      let url: URL;
      try {
        url = new URL(raw);
      } catch {
        return;
      }
      // A passkey sign-in the answer started the app for is finished here; a
      // refused one leaves the sign-in page up, to press again.
      const signedIn = await takeBrowserAnswer(url).catch(() => null);
      if (signedIn) {
        await applySignIn(signedIn);
        await router.navigate({ to: "/", replace: true });
        return;
      }
      if (!isSignInCallback(url)) return;
      const pending = takePendingSignIn(getServerOrigin());
      if (!pending) return;
      await Browser.close().catch(() => undefined);

      const error = url.searchParams.get("error");
      const code = url.searchParams.get("code");
      try {
        if (code) {
          const session = await redeemNativeSignIn(code, pending);
          if (!session) throw new Error("NOT_AUTHENTICATED");
          await completeOidcLogin(session);
        } else {
          throw new Error(error ?? "NOT_AUTHENTICATED");
        }
        await router.navigate({ to: "/", replace: true });
      } catch (err) {
        await router.navigate({
          to: "/oidc/callback",
          search: { error: error ?? (err instanceof Error ? err.message : "NOT_AUTHENTICATED") },
          replace: true,
        });
      }
    };

    void App.getLaunchUrl().then((launch) => {
      if (launch?.url) void handle(launch.url);
    });
    const listener = App.addListener("appUrlOpen", (event: URLOpenListenerEvent) => {
      void handle(event.url);
    });
    return () => {
      void listener.then((l) => l.remove());
    };
  }, [isNativePlatform, getServerOrigin, completeOidcLogin, applySignIn, router]);
}
