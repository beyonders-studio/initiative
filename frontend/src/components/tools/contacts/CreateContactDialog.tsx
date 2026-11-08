import { useState } from "react";
import { useTranslation } from "react-i18next";

import { EndpointKind, RelationshipType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { CreateToolDialog } from "@/components/tools/CreateToolDialog";
import { useContactsList } from "@/hooks/useContacts";
import { useRelate } from "@/hooks/useRelationships";
import { type ContactDetails, filledDetails, NO_DETAILS } from "@/lib/contacts";
import type { DialogProps } from "@/types/dialog";
import { Combobox } from "@/ui/combobox";
import { Field } from "@/ui/field";

import { ContactDetailsFields, ContactKindToggle } from "./ContactDetailsFields";

/** An organization a person can be part of. */
type Organization = { id: number; name: string };

/**
 * The organizations a person may be part of: their initiative's, and the
 * community's own, which an initiative's contacts may link to. A community
 * contact's links stay in the community, so it is offered the community's alone.
 */
const OrganizationPicker = ({
  initiativeId,
  value,
  onChange,
}: {
  initiativeId?: number;
  value: Organization | null;
  onChange: (next: Organization | null) => void;
}) => {
  const { t } = useTranslation("contacts");
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const asked = { is_organization: true, search: search || undefined, page_size: 20 };
  const own = useContactsList(
    { ...asked, initiative_id: initiativeId },
    { enabled: open && initiativeId !== undefined }
  );
  const community = useContactsList({ ...asked, scope: "community" }, { enabled: open });
  const items = [
    ...(initiativeId !== undefined ? (own.data?.items ?? []) : []),
    ...(community.data?.items ?? []).map((org) => ({ ...org, community: true })),
  ];

  return (
    <Combobox
      aria-label={t("partOf")}
      items={[
        { value: "", label: t("noOrganization") },
        ...items.map((org) => ({
          value: String(org.id),
          label: org.name,
          hint: "community" in org ? t("communityHint") : undefined,
        })),
      ]}
      value={value ? String(value.id) : ""}
      selectedLabel={value?.name ?? null}
      onValueChange={(next) => {
        const picked = items.find((org) => String(org.id) === next);
        onChange(picked ? { id: picked.id, name: picked.name } : null);
      }}
      onSearchChange={setSearch}
      onOpenChange={setOpen}
      loading={own.isFetching || community.isFetching}
      placeholder={t("noOrganization")}
      searchPlaceholder={t("searchOrganizations")}
      emptyMessage={t("noOrganizations")}
    />
  );
};

type CreateContactDialogProps = DialogProps & {
  /** The initiative it goes in; omitted for one of the community's own. */
  initiativeId?: number;
  /** The organization a new person is at, already chosen: an organization's
   *  Add person. */
  organization?: Organization;
  onSuccess?: (created: { id: number }) => void;
};

/**
 * A new contact: a person or an organization, how to reach them, and for a
 * person the organization they are at, which is a link rather than a field.
 */
export const CreateContactDialog = ({
  open,
  onOpenChange,
  initiativeId,
  organization: fixedOrganization,
  onSuccess,
}: CreateContactDialogProps) => {
  const { t } = useTranslation("contacts");
  const [isOrganization, setIsOrganization] = useState(false);
  const [details, setDetails] = useState<ContactDetails>(NO_DETAILS);
  const [organization, setOrganization] = useState<Organization | null>(null);

  const [wasOpen, setWasOpen] = useState(open);
  if (wasOpen !== open) {
    setWasOpen(open);
    if (!open) {
      setIsOrganization(false);
      setDetails(NO_DETAILS);
      setOrganization(null);
    }
  }

  const partOf = fixedOrganization ?? (isOrganization ? null : organization);
  const relate = useRelate();

  return (
    <CreateToolDialog
      open={open}
      onOpenChange={onOpenChange}
      tool={Tool.contact}
      text={{
        ns: "contacts",
        create: "newContact",
        createDescription: fixedOrganization ? "addPersonDescription" : "createDescription",
        values: { name: fixedOrganization?.name },
      }}
      initiativeId={initiativeId}
      communityScope={initiativeId === undefined}
      hasDescription={false}
      accessDefaultOpen={false}
      onSuccess={(created) => {
        // The contact is made whether or not the link lands; a refused link
        // says so on its own.
        if (partOf) {
          relate.mutate({
            source: { type: EndpointKind.contact, id: created.id },
            relationship_type: RelationshipType.part_of,
            target: { type: EndpointKind.contact, id: partOf.id },
          });
        }
        onSuccess?.(created);
      }}
      extra={{
        payload: {
          is_organization: fixedOrganization ? false : isOrganization,
          ...filledDetails(details),
        },
        field: (
          <>
            {fixedOrganization ? null : (
              <ContactKindToggle isOrganization={isOrganization} onChange={setIsOrganization} />
            )}

            <ContactDetailsFields value={details} onChange={setDetails} />

            {fixedOrganization || isOrganization ? null : (
              <Field label={t("partOf")}>
                <OrganizationPicker
                  initiativeId={initiativeId}
                  value={organization}
                  onChange={setOrganization}
                />
              </Field>
            )}
          </>
        ),
      }}
    />
  );
};
