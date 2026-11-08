/**
 * "Ask for help" where a notice used to say "contact whoever runs this
 * server": the Help panel, opened on asking the team about the notice's topic
 * where the deployment takes help requests, or on its search with the address
 * it gave where it takes none; nothing where there is neither, leaving the
 * notice's own words.
 */

import type { VariantProps } from "class-variance-authority";
import { useTranslation } from "react-i18next";

import type { SupportTopic } from "@/api/generated/initiativeAPI.schemas";
import { openHelp } from "@/components/help/helpStore";
import { Button, type buttonVariants } from "@/components/ui/button";
import { useTicketAvailability } from "@/hooks/useTickets";
import { cn } from "@/lib/utils";

type ButtonLook = VariantProps<typeof buttonVariants>;

export interface HelpLinkProps {
  /** What the notice is about: the topic the request opens on. */
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
  const { data } = useTicketAvailability(communityId);
  const support = data?.support;
  const form = support?.mode === "form";
  const contact = support?.mode === "email" ? (support.contact ?? null) : null;
  if (!form && !contact) return null;

  return (
    <Button
      type="button"
      variant={variant}
      size={size}
      className={cn(variant === "link" && "h-auto p-0", className)}
      onClick={() => (form ? openHelp({ topic, communityId }) : openHelp())}
    >
      {label ?? t("help.action")}
    </Button>
  );
};
