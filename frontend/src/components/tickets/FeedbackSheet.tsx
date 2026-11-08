/**
 * The feedback sheet: telling the team that makes Initiative about an idea,
 * something that got in the way, or something somebody loves, from wherever
 * they are.
 *
 * Opened by the account menu and the command palette, and drawn once by the
 * app shell. On Initiative Cloud, where feedback lands, it is the sheet, with
 * the form in `FeedbackForm`. From any other server it is Cloud's own page,
 * opened in the browser once Cloud is open, with the device and page it was
 * sent from in the link's fragment, which no server reads until the page
 * sends it.
 *
 * On a wide screen the sheet docks beside the page, which stays in view and in
 * reach; on a phone it is a sheet from the bottom. Closing it keeps what was
 * written until it is sent or discarded.
 *
 * Where feedback is not taken here but an address is set, the sheet is that
 * address; where there is neither, nothing offers it.
 */

import { Suspense, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";

import { type DeviceContext, TicketMode } from "@/api/generated/initiativeAPI.schemas";
import { ContactDialog } from "@/components/tickets/ContactDialog";
import { useDeviceContext } from "@/components/tickets/DeviceContext";
import { EMPTY_DRAFT, type FeedbackDraft, FeedbackForm } from "@/components/tickets/FeedbackForm";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import { useServer } from "@/hooks/useServer";
import { useFileTicket, useTicketAvailability } from "@/hooks/useTickets";
import { CLOUD_OPEN, CLOUD_ORIGIN } from "@/lib/cloud";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { openExternal } from "@/lib/openExternal";
import { atLeast, useWidthClass } from "@/ui/lib/useWidthClass";
import { cn } from "@/ui/lib/utils";
import { Sheet, SheetContent, SheetTitle } from "@/ui/sheet";

// Whether the sheet is open, and what is written in it, kept outside React so
// a menu item and the command palette can open the one drawn by the shell and
// closing it keeps the draft. The draft is its writer's: it opens again only
// for the same account on the same server.
let sheetOpen = false;
let draft: { owner: string; form: FeedbackDraft } | null = null;
const listeners = new Set<() => void>();
const setSheetOpen = (open: boolean) => {
  sheetOpen = open;
  for (const listener of listeners) listener();
};
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

/** Initiative Cloud's feedback page, carrying where it was sent from. */
export const cloudFeedbackLink = (context: DeviceContext): string => {
  const fields = Object.entries(context).filter(
    (entry): entry is [string, string] => typeof entry[1] === "string" && entry[1] !== ""
  );
  return `${CLOUD_ORIGIN}/feedback#${new URLSearchParams(fields)}`;
};

/**
 * Whether this server offers feedback, and what opening it does: the sheet
 * where feedback lands here or an address is set, and Initiative Cloud's page
 * from any other server once Cloud is open.
 */
export const useFeedback = () => {
  const { data } = useTicketAvailability(null);
  const context = useDeviceContext();
  const feedback = data?.feedback;
  const toCloud = feedback?.mode === TicketMode.cloud && CLOUD_OPEN;
  return {
    offered:
      toCloud ||
      feedback?.mode === TicketMode.form ||
      (feedback?.mode === TicketMode.email && Boolean(feedback.contact)),
    open: () => (toCloud ? openExternal(cloudFeedbackLink(context)) : setSheetOpen(true)),
  };
};

/** The sheet, drawn once by the app shell. */
export const FeedbackHost = () => {
  const open = useSyncExternalStore(subscribe, () => sheetOpen);
  if (!open) return null;
  return (
    // Its own boundary: the first opening loads the sheet's translations.
    <Suspense fallback={null}>
      <FeedbackSheet />
    </Suspense>
  );
};

const FeedbackSheet = () => {
  const { t } = useTranslation("intake");
  const communityId = useActiveCommunityId();
  const context = useDeviceContext();
  const { data } = useTicketAvailability(communityId);
  const wide = atLeast(useWidthClass(), "sm");
  const { user } = useAuth();
  const { serverUrl } = useServer();
  const owner = `${serverUrl ?? ""} ${user?.id ?? ""}`;
  const [form, setForm] = useState(draft?.owner === owner ? draft.form : EMPTY_DRAFT);
  const [sent, setSent] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);
  const thanks = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    draft = { owner, form };
  }, [owner, form]);
  useEffect(() => {
    if (sent) thanks.current?.focus();
  }, [sent]);

  const file = useFileTicket({
    onSuccess: () => {
      setSent(true);
      setForm(EMPTY_DRAFT);
    },
    onError: (err) => toast.error(getErrorMessage(err, "intake:feedback.error")),
  });
  const pending = file.isPending;

  const feedback = data?.feedback;
  if (feedback?.mode === TicketMode.email && feedback.contact) {
    return <ContactDialog open onOpenChange={setSheetOpen} contact={feedback.contact} />;
  }
  if (feedback?.mode !== TicketMode.form) return null;

  return (
    // Open until the send settles, so what is being sent is not sent twice.
    <Sheet
      open
      onOpenChange={(open) => {
        if (!pending) setSheetOpen(open);
      }}
      modal={!wide}
    >
      <SheetContent
        side={wide ? "bottom-right" : "bottom"}
        aria-describedby={undefined}
        className={cn("flex flex-col gap-0 p-0", !wide && "max-h-[85dvh] rounded-t-2xl")}
        style={wide ? undefined : { paddingBottom: "var(--safe-area-inset-bottom)" }}
        // Docked beside the page, it stays open while the page is used.
        onInteractOutside={wide ? (event) => event.preventDefault() : undefined}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          box.current?.focus();
        }}
      >
        <FeedbackForm
          Title={SheetTitle}
          draft={form}
          onChange={(next) => setForm((current) => ({ ...current, ...next }))}
          onDiscard={() => setForm(EMPTY_DRAFT)}
          context={context}
          evidence={feedback.evidence}
          help={{ communityId }}
          pending={pending}
          sent={sent}
          submitLabel={t("feedback.submit")}
          onSend={() =>
            file.mutate({
              ticket: {
                stream: "feedback",
                type: form.kind,
                body: form.body.trim(),
                contactable: form.contactable,
                context: form.withContext ? context : null,
              },
              files: form.files,
            })
          }
          onDone={() => setSheetOpen(false)}
          box={box}
          thanks={thanks}
        />
      </SheetContent>
    </Sheet>
  );
};
