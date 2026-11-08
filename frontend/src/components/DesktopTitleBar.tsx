import { Suspense, useEffect, useLayoutEffect, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";

import { AppLinks } from "@/components/AppLinks";
import { LogoIcon } from "@/components/LogoIcon";
import { themeColor } from "@/lib/cssColor";
import Desktop from "@/plugins/desktop";

/** The part of the window controls overlay read here; TypeScript's DOM types lack it. */
interface WindowControlsOverlay extends EventTarget {
  visible: boolean;
  getTitlebarAreaRect(): DOMRect;
}

const overlay = () =>
  (navigator as Navigator & { windowControlsOverlay?: WindowControlsOverlay })
    .windowControlsOverlay;

const subscribe = (listener: () => void) => {
  overlay()?.addEventListener("geometrychange", listener);
  return () => overlay()?.removeEventListener("geometrychange", listener);
};

const titleBarHeight = () => {
  const controls = overlay();
  return controls?.visible ? controls.getTitlebarAreaRect().height : 0;
};

/**
 * The height of the title bar the desktop app leaves the page to draw, or 0
 * where the window draws its own: a browser, a phone, a desktop app from
 * before it drew one, or a window gone full screen.
 */
const useTitleBarHeight = () => useSyncExternalStore(subscribe, titleBarHeight, () => 0);

/** Colour the window's own buttons to the bar, and again whenever the theme or accent changes. */
const useWindowButtonColors = (shown: boolean) => {
  useEffect(() => {
    if (!shown) {
      return;
    }
    let sent = "";
    const send = () => {
      const colors = {
        color: themeColor("--sidebar", "#ffffff"),
        symbolColor: themeColor("--sidebar-foreground", "#020618"),
      };
      const key = `${colors.color} ${colors.symbolColor}`;
      if (key === sent) {
        return;
      }
      sent = key;
      void Desktop.setTitleBarColors(colors).catch(() => {});
    };
    send();
    // The theme is a class on the root, and an accent its inline style.
    const observer = new MutationObserver(send);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class", "style"],
    });
    return () => observer.disconnect();
  }, [shown]);
};

/**
 * The desktop app's title bar, which the window leaves to the page: the app's
 * name, then the app's corner (the update it is waiting on, and Help), with
 * the computer's own window buttons drawn at its end. The bar drags the window
 * and a double click maximizes it. Everything under it is sized by
 * `--title-bar-height` (`h-app`, `min-h-app`, `max-h-app`).
 *
 * It renders on every page, the web included, so it reads only the preloaded
 * `common` namespace; the corner's own translations load inside a boundary.
 */
export const DesktopTitleBar = () => {
  const { t } = useTranslation("common");
  const height = useTitleBarHeight();
  useWindowButtonColors(height > 0);

  // Before paint, so the page is never laid out a bar too tall.
  useLayoutEffect(() => {
    if (!height) {
      return;
    }
    const root = document.documentElement;
    root.style.setProperty("--title-bar-height", `${height}px`);
    return () => {
      root.style.removeProperty("--title-bar-height");
    };
  }, [height]);

  if (!height) {
    return null;
  }

  return (
    <header className="relative shrink-0 border-b bg-sidebar [app-region:drag]" style={{ height }}>
      {/* The stretch of the bar the window's buttons leave free: from the
          Mac's traffic lights to the Windows and Linux buttons. */}
      <div className="absolute inset-y-0 left-[env(titlebar-area-x,0px)] flex w-[env(titlebar-area-width,100%)] items-center gap-2 px-3">
        <LogoIcon className="size-4 shrink-0" aria-hidden="true" focusable="false" />
        <span className="truncate font-medium text-sidebar-foreground text-xs">{t("appName")}</span>
        <Suspense fallback={null}>
          <AppLinks className="ml-auto [app-region:no-drag]" />
        </Suspense>
      </div>
    </header>
  );
};
