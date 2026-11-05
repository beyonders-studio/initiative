import { useParams } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolSettingsLayout } from "@/components/tools/settings/ToolSettingsLayout";
import { useContact, useDeleteContact, useSetContactGrants } from "@/hooks/useContacts";

/** A contact's settings: its sharing, export and deletion. Its name and how to
 *  reach them are edited on its own page, and it carries no description. */
export function ContactSettingsPage() {
  const { contactId } = useParams({ strict: false }) as { contactId?: string };
  const parsedId = contactId ? Number(contactId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);

  const contactQuery = useContact(isValidId ? parsedId : null);
  const setGrants = useSetContactGrants(parsedId);
  const remove = useDeleteContact();

  return (
    <ToolSettingsLayout
      tool={Tool.contact}
      entity={contactQuery.data}
      isLoading={isValidId && contactQuery.isLoading}
      isError={!isValidId || contactQuery.isError}
      setGrants={setGrants}
      remove={remove}
    />
  );
}
