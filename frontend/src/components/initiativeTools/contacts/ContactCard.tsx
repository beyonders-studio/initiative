import { Link } from "@tanstack/react-router";
import { Building2, Mail, Phone, UserRound } from "lucide-react";
import { useTranslation } from "react-i18next";

import { type ContactSummary, EndpointKind, Tool } from "@/api/generated/initiativeAPI.schemas";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { useRelationshipsFor } from "@/hooks/useRelationships";
import { useCommunityPath } from "@/lib/communityUrl";
import { organizationOf } from "@/lib/contacts";
import { getInitials } from "@/lib/initials";
import { toolDetailRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

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
 * The organization a person is part of, linked, read from their links. An
 * organization, or a person at none, shows nothing.
 */
export const ContactOrganization = ({
  contact,
  className,
}: {
  contact: Pick<ContactSummary, "id" | "is_organization">;
  className?: string;
}) => {
  const gp = useCommunityPath();
  const { data: rows = [] } = useRelationshipsFor(
    { type: EndpointKind.contact, id: contact.id },
    { enabled: !contact.is_organization }
  );
  const organization = organizationOf(rows);
  if (!organization) return null;
  return (
    <Link
      to={gp(toolDetailRoute(Tool.contact, organization.initiative_id, organization.id))}
      className={cn("hover:underline", className)}
    >
      {organization.title}
    </Link>
  );
};

/**
 * One contact in a grid of them: who they are, and the first way to reach
 * them by phone and by email — what somebody looking them up came for.
 */
export const ContactCard = ({ contact }: { contact: ContactSummary }) => {
  const { t } = useTranslation("contacts");
  const gp = useCommunityPath();
  const phone = contact.phones[0]?.value;
  const email = contact.emails[0]?.value;

  return (
    <Link
      to={gp(toolDetailRoute(Tool.contact, contact.initiative_id, contact.id))}
      className="group block w-full overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm transition hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-lg"
    >
      {/* Short of the bookmark the list puts on the card's corner. */}
      <div className="flex items-start gap-3 p-4 pr-14">
        <ContactAvatar contact={contact} />
        <div className="min-w-0 flex-1 space-y-1">
          <h3 className="line-clamp-1 font-semibold text-card-foreground text-lg leading-tight">
            {contact.name}
          </h3>
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
          <TagBadgeList
            tags={contact.tags}
            tagHref={(tag) => gp(`/tags/${tag.id}`)}
            nested
            className="pt-1"
          />
        </div>
      </div>
    </Link>
  );
};
