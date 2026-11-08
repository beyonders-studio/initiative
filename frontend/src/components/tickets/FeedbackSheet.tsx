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

import { Suspense, useSyncExternalStore } from "react";

import { ContactDialog } from "@/components/tickets/ContactDialog";
import { useDeviceContext } from "@/components/tickets/DeviceContext";
import { FileTicketDialog } from "@/components/tickets/FileTicketDialog";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useTicketAvailability } from "@/hooks/useTickets";

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
  const context = useDeviceContext();
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
