import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  EndpointKind,
  RelationshipType,
  type ResourceGrantSchema,
} from "@/api/generated/initiativeAPI.schemas";
import { CreateAccessSection } from "@/components/access/CreateAccessSection";
import { DEFAULT_GRANTS } from "@/components/access/grants";
import {
  ContactDetailsFields,
  ContactKindToggle,
} from "@/components/initiativeTools/contacts/ContactDetailsFields";
import { useContactsList, useCreateContact } from "@/hooks/useContacts";
import { useRelate } from "@/hooks/useRelationships";
import { type ContactDetails, filledDetails, NO_DETAILS } from "@/lib/contacts";
import type { DialogProps } from "@/types/dialog";
import { Button } from "@/ui/button";
import { Combobox } from "@/ui/combobox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";

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
  const { t } = useTranslation(["contacts", "common"]);
  const id = useId();
  const [name, setName] = useState("");
  const [isOrganization, setIsOrganization] = useState(false);
  const [details, setDetails] = useState<ContactDetails>(NO_DETAILS);
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [grants, setGrants] = useState<ResourceGrantSchema[]>([...DEFAULT_GRANTS]);

  const [wasOpen, setWasOpen] = useState(open);
  if (wasOpen !== open) {
    setWasOpen(open);
    if (!open) {
      setName("");
      setIsOrganization(false);
      setDetails(NO_DETAILS);
      setOrganization(null);
      setGrants([...DEFAULT_GRANTS]);
    }
  }

  const partOf = fixedOrganization ?? (isOrganization ? null : organization);
  const relate = useRelate();
  const create = useCreateContact({
    onSuccess: (created) => {
      // The contact is made whether or not the link lands; a refused link says
      // so on its own.
      if (partOf) {
        relate.mutate({
          source: { type: EndpointKind.contact, id: created.id },
          relationship_type: RelationshipType.part_of,
          target: { type: EndpointKind.contact, id: partOf.id },
        });
      }
      onOpenChange(false);
      onSuccess?.(created);
    },
  });

  const pending = create.isPending;
  const canSubmit = name.trim() !== "" && !pending;
  const submit = () => {
    if (!canSubmit) return;
    create.mutate({
      name: name.trim(),
      is_organization: fixedOrganization ? false : isOrganization,
      ...filledDetails(details),
      // Left out for one of the community's own: no initiative is what makes it one.
      ...(initiativeId !== undefined ? { initiative_id: initiativeId } : {}),
      grants,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto bg-card sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("newContact")}</DialogTitle>
          <DialogDescription>
            {fixedOrganization
              ? t("addPersonDescription", { name: fixedOrganization.name })
              : t("createDescription")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor={`${id}-name`}>{t("name")}</Label>
            <Input
              id={`${id}-name`}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("namePlaceholder")}
              maxLength={255}
              autoFocus
            />
          </div>

          {fixedOrganization ? null : (
            <ContactKindToggle isOrganization={isOrganization} onChange={setIsOrganization} />
          )}

          <ContactDetailsFields value={details} onChange={setDetails} />

          {fixedOrganization || isOrganization ? null : (
            <div className="space-y-2">
              <Label>{t("partOf")}</Label>
              <OrganizationPicker
                initiativeId={initiativeId}
                value={organization}
                onChange={setOrganization}
              />
            </div>
          )}

          <CreateAccessSection
            initiativeId={initiativeId ?? null}
            grants={grants}
            onChange={setGrants}
            defaultOpen={false}
          />
        </div>

        <DialogFooter>
          <Button type="button" onClick={submit} pending={pending} disabled={!canSubmit}>
            {pending ? t("creating") : t("newContact")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
