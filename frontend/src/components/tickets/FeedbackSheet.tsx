/**
 * The feedback sheet: telling whoever runs this server what you think, from
 * wherever you are.
 *
 * Opened by the account menu and the command palette, and drawn once by the
 * app shell, so it knows the page it was opened on: that page's route, with
 * every id left out, travels with the feedback beside the app's version, the
 * platform, the language, the theme and the window's width — all shown before
 * sending, and removable.
 *
 * Where feedback is not taken here but an address is set, the sheet is that
 * address; where there is neither, nothing offers it.
 */

import { Capacitor } from "@capacitor/core";
import { useMatches } from "@tanstack/react-router";
import { Suspense, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";

import type { FeedbackContext } from "@/api/generated/initiativeAPI.schemas";
import { ContactDialog } from "@/components/tickets/ContactDialog";
import { FileTicketDialog } from "@/components/tickets/FileTicketDialog";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useTheme } from "@/hooks/useTheme";
import { useTicketAvailability } from "@/hooks/useTickets";
import { useWidthClass } from "@/ui/lib/useWidthClass";

// Whether the sheet is open, kept outside React so a menu item and the
// command palette can open the one drawn by the shell.
let sheetOpen = false;
const listeners = new Set<() => void>();
const setSheetOpen = (open: boolean) => {
  sheetOpen = open;
  for (const listener of listeners) listener();
};
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

/** Open the feedback sheet over whatever page is showing. */
export const openFeedback = () => setSheetOpen(true);

/** Whether this server offers anywhere to send feedback: a form or an address. */
export const useFeedbackOffered = () => {
  const { data } = useTicketAvailability(null);
  const mode = data?.feedback.mode;
  return mode === "form" || (mode === "email" && Boolean(data?.feedback.contact));
};

/** A route id as a template: the pathless layout segments dropped, every id
 *  left as the parameter that names it. */
export const routeTemplate = (routeId: string): string => {
  const kept = routeId.split("/").filter((segment) => segment && !segment.startsWith("_"));
  return `/${kept.join("/")}`;
};

const useFeedbackContext = (): FeedbackContext => {
  const { i18n } = useTranslation();
  const { theme } = useTheme();
  const width = useWidthClass();
  const route = useMatches({ select: (matches) => matches.at(-1)?.routeId ?? "" });
  return {
    app_version: __APP_VERSION__,
    platform: Capacitor.getPlatform(),
    locale: i18n.language,
    theme,
    route: routeTemplate(route),
    viewport: width,
  };
};

/** The sheet, drawn once by the app shell. */
export const FeedbackHost = () => {
  const open = useSyncExternalStore(subscribe, () => sheetOpen);
  if (!open) return null;
  return (
    // Its own boundary: the first opening loads the dialog's translations.
    <Suspense fallback={null}>
      <FeedbackSheet />
    </Suspense>
  );
};

const FeedbackSheet = () => {
  const communityId = useActiveCommunityId();
  // Read as the sheet opens, so the page is the one it was opened on.
  const context = useFeedbackContext();
  const { data } = useTicketAvailability(communityId);
  const feedback = data?.feedback;
  if (feedback?.mode === "form") {
    return (
      <FileTicketDialog
        open
        onOpenChange={setSheetOpen}
        ticket={{ stream: "feedback", context }}
        communityId={communityId}
      />
    );
  }
  if (feedback?.mode === "email" && feedback.contact) {
    return <ContactDialog open onOpenChange={setSheetOpen} contact={feedback.contact} />;
  }
  return null;
};
