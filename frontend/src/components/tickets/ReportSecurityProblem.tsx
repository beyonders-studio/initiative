/**
 * "Report a security problem": telling whoever runs this server about one.
 *
 * Where security reports are taken it opens the form, which files a case the
 * reporter follows under their tickets; where they aren't but an address is
 * set, it shows the address. Where there is neither, nothing is offered here,
 * and ``/.well-known/security.txt`` is a 404 too.
 */

import { ShieldAlert } from "lucide-react";
import { Suspense } from "react";
import { useTranslation } from "react-i18next";

import { ContactDialog } from "@/components/tickets/ContactDialog";
import { FileTicketSheet } from "@/components/tickets/FileTicketSheet";
import { useTicketAvailability } from "@/hooks/useTickets";
import { Button } from "@/ui/button";

/** Whether this server offers anything to report a security problem to. */
export const useSecurityReporting = () => {
  const { data } = useTicketAvailability(null);
  const security = data?.security;
  return {
    form: security?.mode === "form",
    contact: security?.mode === "email" ? (security.contact ?? null) : null,
  };
};

export interface SecurityReportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** The form, or the address, as this server offers. */
export const SecurityReportDialog = ({ open, onOpenChange }: SecurityReportDialogProps) => {
  const { form, contact } = useSecurityReporting();
  if (!open) return null;
  return (
    // Its own boundary: the first opening loads the dialog's translations.
    <Suspense fallback={null}>
      {form ? (
        <FileTicketSheet
          open={open}
          onOpenChange={onOpenChange}
          ticket={{ stream: "security" }}
          communityId={null}
        />
      ) : contact ? (
        <ContactDialog open={open} onOpenChange={onOpenChange} contact={contact} />
      ) : null}
    </Suspense>
  );
};

/** A button that opens it, drawn only where there is somewhere to report. */
export const ReportSecurityProblemButton = ({ onOpen }: { onOpen: () => void }) => {
  const { t } = useTranslation("intake");
  const { form, contact } = useSecurityReporting();
  if (!form && !contact) return null;
  return (
    <Button type="button" variant="outline" onClick={onOpen}>
      <ShieldAlert className="h-4 w-4" aria-hidden="true" />
      {t("security.action")}
    </Button>
  );
};
