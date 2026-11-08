import { useLocation } from "@tanstack/react-router";
import { useEffect, useRef } from "react";

import { useHelpOpen } from "@/components/help/helpStore";
import { useSidebar } from "@/components/sidebar/sidebar";

/**
 * Automatically closes the sidebar on mobile devices after navigation.
 * This improves mobile UX by preventing the sidebar from staying open
 * and obscuring content after the user navigates to a new page.
 *
 * A navigation can opt out via `suppressNextAutoClose()` (e.g. switching
 * communities, which navigates but should leave the sidebar open).
 *
 * Only a change of path counts. React runs this effect again whenever the
 * tree around it is shown after a suspension — a dialog opened from the
 * sidebar that loads its translations, say — and that is not a navigation.
 */
export const useAutoCloseSidebar = () => {
  const pathname = useLocation({ select: (location) => location.pathname });
  const { setOpenMobile, isMobile, consumeAutoCloseSuppression } = useSidebar();
  const lastPath = useRef(pathname);

  useEffect(() => {
    if (lastPath.current === pathname) return;
    lastPath.current = pathname;
    // Always consume so a suppression set on desktop can't leak to a later
    // mobile navigation.
    const suppressed = consumeAutoCloseSuppression();
    if (isMobile && !suppressed) {
      setOpenMobile(false);
    }
  }, [pathname, isMobile, setOpenMobile, consumeAutoCloseSuppression]);

  // Help opens over the page as a sheet of its own on a phone.
  const helpOpen = useHelpOpen();
  useEffect(() => {
    if (helpOpen && isMobile) setOpenMobile(false);
  }, [helpOpen, isMobile, setOpenMobile]);
};
