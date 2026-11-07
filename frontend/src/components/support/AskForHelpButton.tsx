/**
 * "Ask for help", in the sidebar's bottom row.
 *
 * Here wherever there is somebody to ask: where the deployment takes help
 * requests, the form — about the community the reader is in, where it takes
 * them from there, and always about their own account — and where it takes
 * none but has said who to write to, that address. Where there is neither, it
 * is not drawn — the documentation has a button of its own beside it, so a
 * dead end never stands in for one.
 */

import { LifeBuoy } from "lucide-react";
import { Suspense, useState } from "react";
import { useTranslation } from "react-i18next";

import { SupportTopic } from "@/api/generated/initiativeAPI.schemas";
import { ContactDialog } from "@/components/tickets/ContactDialog";
import { FileTicketDialog } from "@/components/tickets/FileTicketDialog";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useTicketAvailability } from "@/hooks/useTickets";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

export const AskForHelpButton = () => {
  const { t } = useTranslation("intake");
  const communityId = useActiveCommunityId();
  const [open, setOpen] = useState(false);
  const { data } = useTicketAvailability(communityId);

  // The sidebar stays mounted across a community switch, so a request opened
  // in one could be sent to the next. Changing community closes it: a help
  // request is about where you were, and carrying the words across would send
  // them to people the writer never meant.
  const [prevCommunityId, setPrevCommunityId] = useState(communityId);
  if (prevCommunityId !== communityId) {
    setPrevCommunityId(communityId);
    setOpen(false);
  }

  const support = data?.support;
  const canAsk = support?.mode === "form";
  const contact = support?.mode === "email" ? support.contact : null;
  // Nobody to ask from here, or no answer yet: nothing is drawn rather than a
  // control that would lead nowhere.
  if (!canAsk && !contact) return null;

  const label = t("help.action");

  return (
    <>
      {/* Its own provider. The sidebar supplies one where this is drawn, but
          carrying one means the control cannot be moved somewhere without. */}
      <TooltipProvider delayDuration={300}>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              className="cursor-pointer text-muted-foreground transition-colors hover:text-foreground"
              aria-label={label}
              onClick={() => setOpen(true)}
            >
              <LifeBuoy className="h-4 w-4" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="top">
            <p>{label}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
      {/* Its own boundary: the first opening loads the dialog's translations,
          and waiting on them should hide nothing but the dialog. */}
      <Suspense fallback={null}>
        {open && canAsk ? (
          // Keyed on the community as well, so nothing typed can outlive the one
          // it was typed in even if the close above were ever missed.
          <FileTicketDialog
            key={communityId}
            open={open}
            onOpenChange={setOpen}
            // About where they are, where that is theirs to ask about;
            // otherwise on their own account.
            ticket={{
              stream: "support",
              topic: support?.types?.includes(SupportTopic.community)
                ? SupportTopic.community
                : SupportTopic.account,
            }}
            communityId={communityId}
          />
        ) : open && contact ? (
          <ContactDialog open={open} onOpenChange={setOpen} contact={contact} />
        ) : null}
      </Suspense>
    </>
  );
};
