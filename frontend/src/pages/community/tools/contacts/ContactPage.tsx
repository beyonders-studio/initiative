import { Link, useNavigate } from "@tanstack/react-router";
import {
  ArrowRightLeft,
  CalendarPlus,
  Globe,
  ListPlus,
  Mail,
  MapPin,
  MoreHorizontal,
  Pencil,
  Phone,
  UserPlus,
} from "lucide-react";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  AdminSurface,
  type ContactRead,
  EndpointKind,
  type RelatedEnd,
  type RelationshipRead,
  RelationshipType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { EntityCard } from "@/components/entities/EntityCard";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { CreateEventDialog } from "@/components/tools/calendars/CreateEventDialog";
import { ContactAvatar } from "@/components/tools/contacts/ContactCard";
import {
  ContactDetailsFields,
  ContactKindToggle,
} from "@/components/tools/contacts/ContactDetailsFields";
import { CreateContactDialog } from "@/components/tools/contacts/CreateContactDialog";
import { ToolAccessStatus } from "@/components/tools/ToolAccessStatus";
import { ToolChest } from "@/components/tools/ToolChest";
import { ToolPageHeader } from "@/components/tools/ToolPageHeader";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useCommunityPlugins } from "@/hooks/useCommunityPlugins";
import { useContact, useMoveContact, useUpdateContact } from "@/hooks/useContacts";
import { useHeldSurfaces } from "@/hooks/useCustomRoles";
import { useInitiative } from "@/hooks/useInitiatives";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useRecordOpen } from "@/hooks/usePersonalItems";
import { useRelate, useRelationshipsFor } from "@/hooks/useRelationships";
import { useRouteId } from "@/hooks/useRouteId";
import { useCommunityPath } from "@/lib/communityUrl";
import {
  CONTACT_DETAILS,
  type ContactDetailField,
  type ContactDetails,
  filledDetails,
  mailtoHref,
  organizationOf,
  peopleOf,
  standingOf,
  telHref,
} from "@/lib/contacts";
import { toast } from "@/lib/mascotToast";
import { toolDetailRoute, toolListRoute, toolSettingsRoute } from "@/lib/tools";
import { Button } from "@/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { CopyButton } from "@/ui/copy-button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";
import { dateTimeFormat } from "@/ui/lib/intl";
import { DetailHeaderSkeleton } from "@/ui/page-skeletons";
import { Skeleton } from "@/ui/skeleton";

import { ContactNewTaskDialog } from "./ContactNewTaskDialog";

/** The icon in front of each kind of detail. */
const DETAIL_ICONS = { phones: Phone, emails: Mail, addresses: MapPin, websites: Globe };

/** One detail as the one tap that uses it: a call, a message, the site, or a
 *  copy of the address. */
const DetailAction = ({ field, value }: { field: ContactDetailField; value: string }) => {
  const { t } = useTranslation("contacts");
  if (field === "addresses") {
    return (
      <div className="flex min-w-0 flex-1 items-start gap-2">
        <address className="min-w-0 flex-1 whitespace-pre-line not-italic">{value}</address>
        <CopyButton value={value} label={t("reach.copy")} copiedMessage={t("reach.copied")} />
      </div>
    );
  }
  const link =
    field === "phones"
      ? { href: telHref(value) }
      : field === "emails"
        ? { href: mailtoHref(value) }
        : { href: value, target: "_blank", rel: "noopener noreferrer" };
  return (
    <a {...link} className="min-w-0 flex-1 break-words text-primary hover:underline">
      {value}
    </a>
  );
};

/** How to reach them, each detail one tap from use, and editable in place by
 *  whoever may change the contact. */
const ContactReach = ({ contact }: { contact: ContactRead }) => {
  const { t } = useTranslation(["contacts", "common"]);
  const [draft, setDraft] = useState<(ContactDetails & { is_organization: boolean }) | null>(null);
  const update = useUpdateContact(contact.id, {
    onSuccess: () => {
      setDraft(null);
      toast.success(t("details.saved"));
    },
  });
  const empty = CONTACT_DETAILS.every((field) => contact[field].length === 0);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
        <CardTitle className="text-base">{t("details.title")}</CardTitle>
        {contact.can.edit && !draft ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() =>
              setDraft({
                is_organization: contact.is_organization,
                phones: contact.phones,
                emails: contact.emails,
                addresses: contact.addresses,
                websites: contact.websites,
              })
            }
          >
            <Pencil className="h-4 w-4" />
            {t("details.edit")}
          </Button>
        ) : null}
      </CardHeader>
      <CardContent>
        {draft ? (
          <div className="space-y-4">
            <ContactKindToggle
              isOrganization={draft.is_organization}
              onChange={(is_organization) => setDraft({ ...draft, is_organization })}
            />
            <ContactDetailsFields
              value={draft}
              onChange={(next) => setDraft({ ...draft, ...next })}
            />
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setDraft(null)}>
                {t("common:cancel")}
              </Button>
              <Button
                type="button"
                disabled={update.isPending}
                onClick={() =>
                  update.mutate({ is_organization: draft.is_organization, ...filledDetails(draft) })
                }
              >
                {t("common:save")}
              </Button>
            </div>
          </div>
        ) : empty ? (
          <p className="text-muted-foreground text-sm">{t("details.empty")}</p>
        ) : (
          <dl className="space-y-3 text-sm">
            {CONTACT_DETAILS.flatMap((field) =>
              contact[field].map((detail, index) => {
                const Icon = DETAIL_ICONS[field];
                return (
                  // biome-ignore lint/suspicious/noArrayIndexKey: positional by nature
                  <div key={`${field}-${index}`} className="flex items-start gap-3">
                    <dt className="flex w-24 shrink-0 items-center gap-2 text-muted-foreground">
                      <Icon className="h-4 w-4 shrink-0" aria-hidden />
                      <span className="truncate">{detail.label || t(`fields.${field}`)}</span>
                    </dt>
                    <dd className="flex min-w-0 flex-1">
                      <DetailAction field={field} value={detail.value} />
                    </dd>
                  </div>
                );
              })
            )}
          </dl>
        )}
      </CardContent>
    </Card>
  );
};

/** A list of linked things under a heading, or nothing when there are none. */
const StandingGroup = ({
  title,
  ends,
  badge,
}: {
  title: string;
  ends: RelatedEnd[];
  badge?: (end: RelatedEnd) => string;
}) =>
  ends.length > 0 ? (
    <section className="space-y-2">
      <h3 className="font-medium text-muted-foreground text-xs">{title}</h3>
      <ul aria-label={title} className="space-y-1.5">
        {ends.map((end) => (
          <li key={`${end.type}:${end.id}`}>
            <EntityCard variant="compact" end={end} badge={badge?.(end)} />
          </li>
        ))}
      </ul>
    </section>
  ) : null;

/**
 * Where things stand with them, read from their links: the open tasks, what is
 * coming up, and their files. New work starts here already linked, in the
 * contact's initiative; a community contact's links run from the initiatives'
 * side, so it starts none.
 */
const ContactStanding = ({ contact, links }: { contact: ContactRead; links: RelatedLinks }) => {
  const { t, i18n } = useTranslation("contacts");
  const [adding, setAdding] = useState<"task" | "event" | null>(null);
  const [now] = useState(() => new Date());
  const standing = standingOf(links.rows, now);
  const contactRef = { type: EndpointKind.contact, id: contact.id };
  const relate = useRelate(
    { tool: Tool.contact, id: contact.id },
    { onSuccess: () => toast.success(t("linked", { name: contact.name })) }
  );
  const link = (type: typeof EndpointKind.task | typeof EndpointKind.calendar_event, id: number) =>
    relate.mutate({
      source: contactRef,
      relationship_type: RelationshipType.related_to,
      target: { type, id },
    });
  const when = (end: RelatedEnd) =>
    dateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" }).format(
      new Date(end.starts_at ?? 0)
    );
  const initiativeId = contact.initiative_id;
  const nothing =
    standing.openTasks.length + standing.upcoming.length + standing.files.length === 0;

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 space-y-0">
        <CardTitle className="text-base">{t("standing.title")}</CardTitle>
        {initiativeId !== null ? (
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => setAdding("task")}>
              <ListPlus className="h-4 w-4" />
              {t("newTask")}
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => setAdding("event")}>
              <CalendarPlus className="h-4 w-4" />
              {t("newEvent")}
            </Button>
          </div>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-4">
        {links.isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : nothing ? (
          <p className="text-muted-foreground text-sm">{t("standing.empty")}</p>
        ) : (
          <>
            <StandingGroup title={t("standing.openTasks")} ends={standing.openTasks} />
            <StandingGroup title={t("standing.upcoming")} ends={standing.upcoming} badge={when} />
            <StandingGroup title={t("standing.files")} ends={standing.files} />
          </>
        )}
      </CardContent>
      {initiativeId !== null ? (
        <>
          <ContactNewTaskDialog
            open={adding === "task"}
            onOpenChange={(open) => setAdding(open ? "task" : null)}
            contact={{ name: contact.name, initiative_id: initiativeId }}
            onCreated={(task) => link(EndpointKind.task, task.id)}
          />
          {adding === "event" ? (
            <CreateEventDialog
              open
              onOpenChange={(open) => setAdding(open ? "event" : null)}
              initiativeId={initiativeId}
              onSuccess={(event) => link(EndpointKind.calendar_event, event.id)}
            />
          ) : null}
        </>
      ) : null}
    </Card>
  );
};

/** An organization's people: the contacts `part_of` it, and a way to add one
 *  already at it, where the reader may add contacts. */
const ContactPeople = ({
  contact,
  links,
  canAdd,
}: {
  contact: ContactRead;
  links: RelatedLinks;
  canAdd: boolean;
}) => {
  const { t } = useTranslation("contacts");
  const gp = useCommunityPath();
  const navigate = useNavigate();
  const [adding, setAdding] = useState(false);
  const people = peopleOf(links.rows);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
        <CardTitle className="text-base">{t("people.title")}</CardTitle>
        {canAdd ? (
          <Button type="button" variant="outline" size="sm" onClick={() => setAdding(true)}>
            <UserPlus className="h-4 w-4" />
            {t("people.add")}
          </Button>
        ) : null}
      </CardHeader>
      <CardContent>
        {people.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("people.empty")}</p>
        ) : (
          <ul aria-label={t("people.title")} className="divide-y">
            {people.map((person) => (
              <li key={person.id} className="py-2 first:pt-0 last:pb-0">
                <Link
                  to={gp(toolDetailRoute(Tool.contact, person.initiative_id, person.id))}
                  className="flex items-center gap-3 hover:underline"
                >
                  <ContactAvatar
                    contact={{ name: person.title ?? "", is_organization: false }}
                    className="size-8"
                  />
                  <span className="min-w-0 truncate font-medium text-sm">{person.title}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
      {canAdd ? (
        <CreateContactDialog
          open={adding}
          onOpenChange={setAdding}
          initiativeId={contact.initiative_id ?? undefined}
          organization={{ id: contact.id, name: contact.name }}
          onSuccess={(created) =>
            void navigate({
              to: gp(toolDetailRoute(Tool.contact, contact.initiative_id, created.id)),
            })
          }
        />
      ) : null}
    </Card>
  );
};

/** A contact's links, read once for every part of the page that reads them. */
type RelatedLinks = { rows: RelationshipRead[]; isLoading: boolean };

/**
 * One contact: who they are and how to reach them, where things stand with
 * them, and for an organization, its people. Its links, comments, tags and
 * sharing are every tool's.
 */
export function ContactPage() {
  const { t } = useTranslation(["contacts", "common"]);
  const contactId = useRouteId("contactId");
  const gp = useCommunityPath();
  const navigate = useNavigate();
  const contactQuery = useContact(contactId);
  const contact = contactQuery.data;
  const initiativeId = useCanonicalInitiativeId(contact?.initiative_id);
  useReadOnOpen(Tool.contact, contact?.id);
  useRecordOpen(Tool.contact, contact?.id);
  const canEdit = Boolean(contact?.can.edit);
  const rename = useUpdateContact(contactId ?? 0, {
    onSuccess: () => toast.success(t("details.saved")),
  });
  const linksQuery = useRelationshipsFor(
    { type: EndpointKind.contact, id: contactId ?? 0 },
    { enabled: contactId !== null }
  );
  const links: RelatedLinks = { rows: linksQuery.data ?? [], isLoading: linksQuery.isLoading };
  const organization = organizationOf(links.rows);

  // Who may add one beside it: the initiative's role, or for the community's
  // own, holding its contacts with the plug-in there to hold them.
  const holdsCommunityContacts = useHeldSurfaces().holds(AdminSurface.community_contacts);
  const hasPlugin = Boolean(
    useCommunityPlugins().data?.items.some((plugin) => plugin.tool === Tool.contact)
  );
  const mayAddToCommunity = holdsCommunityContacts && hasPlugin;
  const initiative = useInitiative(contact?.initiative_id ?? null).data;
  const canAddPeople =
    contact?.initiative_id == null
      ? mayAddToCommunity
      : Boolean(initiative?.can.create.includes(Tool.contact));

  const [moving, setMoving] = useState(false);
  const move = useMoveContact(contactId ?? 0, {
    onSuccess: (moved) => {
      setMoving(false);
      toast.success(t("move.moved"));
      void navigate({ to: gp(toolDetailRoute(Tool.contact, moved.initiative_id, moved.id)) });
    },
  });

  if (contactId === null || contactQuery.isError) {
    return (
      <ToolAccessStatus
        error={contactQuery.error}
        keys="contacts:"
        backTo={gp(toolListRoute(Tool.contact, initiativeId))}
        backLabel={t("backToContacts")}
        entity={contactId === null ? undefined : { kind: "contact", id: contactId }}
      />
    );
  }

  // Moving needs write on it, and the community's contacts to move it into.
  const canMove = Boolean(
    contact && contact.initiative_id !== null && canEdit && mayAddToCommunity
  );
  const kindLine: ReactNode = contact ? (
    <p className="flex flex-wrap items-center gap-x-1.5 text-muted-foreground text-sm">
      <span>{t(contact.is_organization ? "organization" : "person")}</span>
      {organization ? (
        <>
          <span aria-hidden>·</span>
          <Link
            to={gp(toolDetailRoute(Tool.contact, organization.initiative_id, organization.id))}
            className="text-foreground hover:underline"
          >
            {organization.title}
          </Link>
        </>
      ) : null}
    </p>
  ) : null;

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6">
      {contact ? (
        <ToolPageHeader
          tool={Tool.contact}
          initiativeId={contact.initiative_id}
          starId={contact.id}
          settingsTo={
            canEdit ? toolSettingsRoute(Tool.contact, initiativeId, contact.id) : undefined
          }
          mark={<ContactAvatar contact={contact} />}
          chest={<ToolChest tool={Tool.contact} entity={contact} />}
          title={contact.name}
          onRename={canEdit ? (name) => rename.mutateAsync({ name }) : undefined}
          titleExtras={
            canMove ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    aria-label={t("common:toolbar.moreActions")}
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => setMoving(true)}>
                    <ArrowRightLeft className="h-4 w-4" />
                    {t("move.action")}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null
          }
        >
          {kindLine}
        </ToolPageHeader>
      ) : (
        <DetailHeaderSkeleton actions={0} description={false} />
      )}

      {contact ? (
        <div className="grid grid-cols-fill-80/2 items-start gap-6">
          <ContactReach key={contact.id} contact={contact} />
          <ContactStanding contact={contact} links={links} />
          {contact.is_organization ? (
            <ContactPeople contact={contact} links={links} canAdd={canAddPeople} />
          ) : null}
        </div>
      ) : (
        <Skeleton className="h-40 w-full" />
      )}

      <ToolRelationsPanel
        tool={Tool.contact}
        entity={contact}
        canEdit={canEdit}
        entityTitle={contact?.name}
      />
      {contact ? <ToolCommentsPanel tool={Tool.contact} entity={contact} /> : null}

      {contact ? (
        <ConfirmDialog
          open={moving}
          onOpenChange={setMoving}
          title={t("move.title", { name: contact.name })}
          description={t("move.description")}
          confirmLabel={t("move.confirm")}
          onConfirm={() => move.mutate()}
          isLoading={move.isPending}
          loadingLabel={t("move.moving")}
        />
      ) : null}
    </div>
  );
}
