import { Building2, Mail, Phone, UserRound } from "lucide-react";
import { useTranslation } from "react-i18next";

import { type ContactSummary, Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolCard } from "@/components/tools/ToolCard";
import { getInitials } from "@/lib/initials";
import { toolDetailRoute } from "@/lib/tools";
import { Avatar, AvatarFallback } from "@/ui/avatar";
import { cn } from "@/ui/lib/utils";

type ContactKind = Pick<ContactSummary, "name" | "is_organization">;

/** A contact's initials, round for a person and square for an organization. */
export const ContactAvatar = ({
  contact,
  className,
}: {
  contact: ContactKind;
  className?: string;
}) => (
  <Avatar className={cn("size-10 border", contact.is_organization && "rounded-lg", className)}>
    <AvatarFallback className={cn(contact.is_organization && "rounded-lg")}>
      {getInitials(contact.name)}
    </AvatarFallback>
  </Avatar>
);

/** Whether a contact is a person or an organization, as an icon in front of
 *  its name. */
export const ContactMark = ({ contact }: { contact: ContactKind }) => {
  const { t } = useTranslation("contacts");
  const Icon = contact.is_organization ? Building2 : UserRound;
  return (
    <Icon
      className="h-4 w-4 shrink-0 text-muted-foreground"
      role="img"
      aria-label={t(contact.is_organization ? "organization" : "person")}
    />
  );
};

/**
 * One contact in a grid of them: who they are, and the first way to reach
 * them by phone and by email — what somebody looking them up came for.
 */
export const ContactCard = ({ contact }: { contact: ContactSummary }) => {
  const { t } = useTranslation("contacts");
  const phone = contact.phones[0]?.value;
  const email = contact.emails[0]?.value;

  return (
    <ToolCard
      to={toolDetailRoute(Tool.contact, contact.initiative_id, contact.id)}
      name={contact.name}
      tags={contact.tags}
      mark={<ContactAvatar contact={contact} />}
    >
      <p className="text-muted-foreground text-xs">
        {t(contact.is_organization ? "organization" : "person")}
      </p>
      {phone || email ? (
        <div className="space-y-0.5 pt-1 text-sm">
          {phone ? (
            <p className="flex items-center gap-1.5 truncate">
              <Phone className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
              {phone}
            </p>
          ) : null}
          {email ? (
            <p className="flex items-center gap-1.5 truncate">
              <Mail className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <span className="truncate">{email}</span>
            </p>
          ) : null}
        </div>
      ) : null}
    </ToolCard>
  );
};
