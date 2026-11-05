import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { ContactDetail, ContactSummary } from "@/api/generated/initiativeAPI.schemas";
import { ContactOrganization } from "@/components/initiativeTools/contacts/ContactCard";
import { mailtoHref, telHref } from "@/lib/contacts";
import type { AppColumnDef } from "@/lib/table";

const NONE = <span className="text-muted-foreground">—</span>;

/** A contact's first detail of one kind, as a link that reaches them. */
const FirstDetail = ({
  details,
  href,
}: {
  details: ContactDetail[];
  href: (value: string) => string;
}) => {
  const [first] = details;
  if (!first) return NONE;
  return (
    <a href={href(first.value)} className="whitespace-nowrap hover:underline">
      {first.value}
    </a>
  );
};

/** What the contacts table shows beside the columns every tool's table has:
 *  the first phone and email, one tap from a call or a message, and the
 *  organization a person is at. */
export const useContactColumns = (): AppColumnDef<ContactSummary>[] => {
  const { t } = useTranslation("contacts");

  return useMemo<AppColumnDef<ContactSummary>[]>(
    () => [
      {
        id: "phone",
        header: t("columns.phone"),
        cell: ({ row }) => <FirstDetail details={row.original.phones} href={telHref} />,
      },
      {
        id: "email",
        header: t("columns.email"),
        cell: ({ row }) => <FirstDetail details={row.original.emails} href={mailtoHref} />,
      },
      {
        id: "organization",
        header: t("columns.organization"),
        cell: ({ row }) => <ContactOrganization contact={row.original} />,
      },
    ],
    [t]
  );
};
