/**
 * "Ask for help" where a notice used to say "contact whoever runs this
 * server": the help form, opened on the topic the notice is about, where the
 * deployment takes help requests; the address it gave where it takes none;
 * and nothing where there is neither, leaving the notice's own words.
 */

import type { VariantProps } from "class-variance-authority";
import { Suspense, useState } from "react";
import { useTranslation } from "react-i18next";

import type { SupportTopic } from "@/api/generated/initiativeAPI.schemas";
import { ContactDialog } from "@/components/tickets/ContactDialog";
import { FileTicketDialog } from "@/components/tickets/FileTicketDialog";
import { useTicketAvailability } from "@/hooks/useTickets";
import { Button, type buttonVariants } from "@/ui/button";
import { cn } from "@/ui/lib/utils";

type ButtonLook = VariantProps<typeof buttonVariants>;

export interface HelpLinkProps {
  /** What the notice is about: the topic the form opens on. */
  topic: SupportTopic;
  /** The community the notice is about, where it is about one. */
  communityId: number | null;
  /** The button's words. "Ask for help" when not given. */
  label?: string;
  variant?: ButtonLook["variant"];
  size?: ButtonLook["size"];
  className?: string;
}

export const HelpLink = ({
  topic,
  communityId,
  label,
  variant = "link",
  size = "sm",
  className,
}: HelpLinkProps) => {
  const { t } = useTranslation("intake");
  const [open, setOpen] = useState(false);
  const { data } = useTicketAvailability(communityId);
  const support = data?.support;
  const form = support?.mode === "form";
  const contact = support?.mode === "email" ? (support.contact ?? null) : null;
  if (!form && !contact) return null;

  return (
    <>
      <Button
        type="button"
        variant={variant}
        size={size}
        className={cn(variant === "link" && "h-auto p-0", className)}
        onClick={() => setOpen(true)}
      >
        {label ?? t("help.action")}
      </Button>
      {open ? (
        // Its own boundary: the first opening loads the dialog's translations.
        <Suspense fallback={null}>
          {form ? (
            <FileTicketDialog
              open
              onOpenChange={setOpen}
              ticket={{ stream: "support", topic }}
              communityId={communityId}
            />
          ) : contact ? (
            <ContactDialog open onOpenChange={setOpen} contact={contact} />
          ) : null}
        </Suspense>
      ) : null}
    </>
  );
};
