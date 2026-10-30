import { Link } from "@tanstack/react-router";
import { CalendarPlus, RefreshCcw, UserCheck, UserMinus, X } from "lucide-react";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CommunityInviteGrant,
  CommunityInviteGrantLevel,
  CommunityInviteRead,
  SearchSuggestion,
  Tool,
  UserCommunityMember,
} from "@/api/generated/initiativeAPI.schemas";
import {
  CommunityInviteList,
  InviteLimitFields,
  NewInviteLink,
} from "@/components/communities/CommunityInvites";
import { RemoveCommunityMemberDialog } from "@/components/communities/RemoveCommunityMemberDialog";
import { EntityPicker } from "@/components/entities/EntityPicker";
import { SkeletonRegion, TableSkeleton } from "@/components/skeletons/PageSkeletons";
import { UserHandle } from "@/components/UserHandle";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { RelativeTime } from "@/components/ui/relative-time";
import { RowActionsMenu } from "@/components/ui/row-actions-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useCommunities } from "@/hooks/useCommunities";
import { useCommunityInvites } from "@/hooks/useCommunityInvites";
import { useHeldSurfaces } from "@/hooks/useCustomRoles";
import { useCommunityInitiatives } from "@/hooks/useInitiatives";
import { useServerTableState } from "@/hooks/useServerTableState";
import { useExtendGuest, useMakeGuestAMember, useUsers } from "@/hooks/useUsers";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import type { AppColumnDef } from "@/lib/table";
import { TOOLS } from "@/lib/tools";
import { getUrlHandle, getUserDisplayName } from "@/lib/userDisplay";

/** One item a guest invite gives, and how far. */
interface ChosenItem {
  suggestion: SearchSuggestion;
  level: NonNullable<CommunityInviteGrantLevel>;
}

const itemKey = (item: SearchSuggestion) => `${item.entity_type}:${item.entity_id}`;

const ExtendGuestDialog = ({
  communityId,
  guest,
  onOpenChange,
}: {
  communityId: number;
  guest: UserCommunityMember | null;
  onOpenChange: (open: boolean) => void;
}) => {
  const { t } = useTranslation(["communities", "common"]);
  const [days, setDays] = useState(7);
  const extend = useExtendGuest({
    onSuccess: () => {
      toast.success(t("guests.extended"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(getErrorMessage(error, "communities:guests.extendError")),
  });

  useEffect(() => {
    if (guest) setDays(7);
  }, [guest]);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (guest) extend.mutate({ communityId, userId: guest.id, days });
  };

  return (
    <Dialog open={guest !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t("guests.extendTitle", { name: guest ? getUserDisplayName(guest) : "" })}
          </DialogTitle>
          <DialogDescription>{t("guests.extendDescription")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={submit}>
          <div className="space-y-2">
            <Label htmlFor="extend-guest-days">{t("guests.extendDaysLabel")}</Label>
            <Input
              id="extend-guest-days"
              type="number"
              min={1}
              value={days}
              onChange={(event) => setDays(Number(event.target.value))}
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              {t("common:cancel")}
            </Button>
            <Button type="submit" disabled={days < 1 || extend.isPending}>
              {t("guests.extend")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

/**
 * Community settings › Guests: the people here for a set number of days, and
 * the invites that bring them. A guest takes no seat and reaches only the
 * initiatives and items their invite gave them.
 */
export const SettingsCommunityGuestsPage = () => {
  const { t } = useTranslation(["communities", "access", "common"]);
  const { activeCommunity } = useCommunities();
  const { guestsEnabled } = useAppConfig();
  const communityId = activeCommunity?.id ?? null;
  // Whoever hands out invites on the admin rung, where the deployment and the
  // community both take guests: a guest invite can open any initiative.
  // Changing a guest's stay is running the roster.
  const held = useHeldSurfaces();
  const managesGuests =
    held.writes &&
    held.holds("invites") &&
    Boolean(activeCommunity?.can.administer) &&
    guestsEnabled &&
    activeCommunity?.max_guests !== 0;
  const managesMembers = held.holds("members");

  const table = useServerTableState();
  const guestsQuery = useUsers({ ...table.params, guests: true }, { enabled: managesGuests });
  const guests = guestsQuery.data?.items ?? [];

  const invites = useCommunityInvites(communityId, managesGuests);
  const guestInvites = invites.invites.filter((invite) => invite.guest_days != null);
  const [inviteLimits, setInviteLimits] = useState({ maxUses: 1, expiresDays: 7 });
  const [guestDays, setGuestDays] = useState(7);
  const [initiativeIds, setInitiativeIds] = useState<string[]>([]);
  const [items, setItems] = useState<ChosenItem[]>([]);

  const initiativesQuery = useCommunityInitiatives({ enabled: managesGuests });
  const initiativeNames = useMemo(
    () => new Map((initiativesQuery.data ?? []).map((row) => [row.id, row.name])),
    [initiativesQuery.data]
  );

  const [extending, setExtending] = useState<UserCommunityMember | null>(null);
  const [removing, setRemoving] = useState<{ userId: number; name: string } | null>(null);
  const makeMember = useMakeGuestAMember({
    onSuccess: () => toast.success(t("guests.madeMember")),
    onError: (error) => toast.error(getErrorMessage(error, "communities:guests.makeMemberError")),
  });

  if (!managesGuests || communityId === null) {
    return <p className="text-muted-foreground text-sm">{t("users.adminRequired")}</p>;
  }

  const addItem = (suggestion: SearchSuggestion | null) => {
    if (!suggestion || suggestion.initiative_id == null) return;
    if (items.some((item) => itemKey(item.suggestion) === itemKey(suggestion))) return;
    setItems([...items, { suggestion, level: "read" }]);
  };

  const createInvite = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const grants: CommunityInviteGrant[] = [
      ...initiativeIds.map((id) => ({ initiative_id: Number(id) })),
      ...items.map(({ suggestion, level }) => ({
        initiative_id: suggestion.initiative_id as number,
        resource_type: suggestion.entity_type as Tool,
        resource_id: suggestion.entity_id,
        level,
      })),
    ];
    await invites.create(inviteLimits, { guest_days: guestDays, grants });
  };

  /** What one guest invite gives: its days, and the initiatives and items. */
  const inviteGives = (invite: CommunityInviteRead) => {
    const joins = invite.grants
      .filter((grant) => grant.resource_type == null)
      .map((grant) => initiativeNames.get(grant.initiative_id))
      .filter((name): name is string => Boolean(name));
    const itemCount = invite.grants.filter((grant) => grant.resource_type != null).length;
    return (
      <p className="text-muted-foreground">
        {[
          t("guests.staysDays", { count: invite.guest_days ?? 0 }),
          joins.length ? t("guests.joinsInitiatives", { names: joins.join(", ") }) : null,
          itemCount ? t("guests.givesItems", { count: itemCount }) : null,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
    );
  };

  const columns: AppColumnDef<UserCommunityMember>[] = [
    {
      id: "username",
      header: t("users.handleColumn"),
      cell: ({ row }) => (
        <Link
          to="/u/$handle"
          params={{ handle: getUrlHandle(row.original) }}
          className="text-sm hover:underline"
        >
          <UserHandle user={row.original} />
        </Link>
      ),
    },
    {
      accessorKey: "guest_until",
      header: t("guests.endsColumn"),
      cell: ({ row }) => <RelativeTime date={row.original.guest_until} className="text-sm" />,
    },
    ...(managesMembers
      ? [
          {
            id: "actions",
            header: t("users.actionsColumn"),
            cell: ({ row }) => {
              const guest = row.original;
              return (
                <RowActionsMenu subject={getUserDisplayName(guest)}>
                  <DropdownMenuItem onSelect={() => setExtending(guest)}>
                    <CalendarPlus className="h-4 w-4" />
                    {t("guests.extend")}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    disabled={makeMember.isPending}
                    onSelect={() => makeMember.mutate({ communityId, userId: guest.id })}
                  >
                    <UserCheck className="h-4 w-4" />
                    {t("guests.makeMember")}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="text-destructive"
                    onSelect={() =>
                      setRemoving({ userId: guest.id, name: getUserDisplayName(guest) })
                    }
                  >
                    <UserMinus className="h-4 w-4" />
                    {t("users.removeFromCommunity")}
                  </DropdownMenuItem>
                </RowActionsMenu>
              );
            },
          } satisfies AppColumnDef<UserCommunityMember>,
        ]
      : []),
  ];

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>{t("guests.invitesTitle")}</CardTitle>
            <CardDescription>{t("guests.invitesDescription")}</CardDescription>
          </div>
          <Button variant="ghost" size="icon" onClick={invites.refresh}>
            <RefreshCcw className="h-4 w-4" />
            <span className="sr-only">{t("users.refreshInvites")}</span>
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <form className="space-y-4" onSubmit={createInvite}>
            <div className="grid grid-cols-fill-48/3 gap-4">
              <div className="space-y-2">
                <Label htmlFor="guest-days">{t("guests.guestDaysLabel")}</Label>
                <Input
                  id="guest-days"
                  type="number"
                  min={1}
                  value={guestDays}
                  onChange={(event) => setGuestDays(Number(event.target.value))}
                />
              </div>
              <InviteLimitFields
                idPrefix="guest-invite"
                value={inviteLimits}
                onChange={setInviteLimits}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="guest-initiatives">{t("guests.initiativesLabel")}</Label>
              <MultiSelect
                id="guest-initiatives"
                selectedValues={initiativeIds}
                options={(initiativesQuery.data ?? []).map((row) => ({
                  value: String(row.id),
                  label: row.name,
                }))}
                onChange={setInitiativeIds}
                placeholder={t("guests.initiativesPlaceholder")}
                className="w-full max-w-72"
              />
            </div>
            <div className="space-y-2">
              <p className="font-medium text-sm">{t("guests.itemsLabel")}</p>
              <p className="text-muted-foreground text-sm">{t("guests.itemsHelp")}</p>
              <EntityPicker initiativeId={null} types={TOOLS} value={null} onChange={addItem} />
              {items.map(({ suggestion, level }) => (
                <div
                  key={itemKey(suggestion)}
                  className="flex flex-wrap items-center justify-between gap-2 rounded border px-3 py-2 text-sm"
                >
                  <div className="min-w-0">
                    <p className="font-medium">{suggestion.title}</p>
                    {suggestion.initiative_name ? (
                      <p className="text-muted-foreground text-xs">{suggestion.initiative_name}</p>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-2">
                    <Select
                      value={level}
                      onValueChange={(next) =>
                        setItems(
                          items.map((item) =>
                            item.suggestion === suggestion
                              ? { ...item, level: next as ChosenItem["level"] }
                              : item
                          )
                        )
                      }
                    >
                      <SelectTrigger
                        className="w-32"
                        aria-label={t("guests.itemLevel", { title: suggestion.title })}
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="read">{t("access:share.viewer")}</SelectItem>
                        <SelectItem value="write">{t("access:share.editor")}</SelectItem>
                      </SelectContent>
                    </Select>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() =>
                        setItems(items.filter((item) => item.suggestion !== suggestion))
                      }
                    >
                      <X className="h-4 w-4" />
                      <span className="sr-only">
                        {t("guests.removeItem", { title: suggestion.title })}
                      </span>
                    </Button>
                  </div>
                </div>
              ))}
            </div>
            <Button type="submit" disabled={invites.submitting || guestDays < 1}>
              {invites.submitting ? t("users.generatingInvite") : t("guests.generateInvite")}
            </Button>
          </form>
          {invites.newInviteCode ? <NewInviteLink code={invites.newInviteCode} /> : null}
          <div className="h-px bg-border" />
          <CommunityInviteList
            invites={guestInvites}
            isLoading={invites.isLoading}
            error={invites.error}
            emptyText={t("guests.noActiveInvites")}
            onDelete={(inviteId) => void invites.remove(inviteId)}
            detail={inviteGives}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("guests.listTitle")}</CardTitle>
          <CardDescription>{t("guests.listDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {guestsQuery.isLoading ? (
            <SkeletonRegion label={t("guests.loading")}>
              <TableSkeleton rows={3} columns={3} />
            </SkeletonRegion>
          ) : guestsQuery.isError ? (
            <p className="text-destructive text-sm">{t("guests.unableToLoad")}</p>
          ) : guests.length === 0 && !table.params.search ? (
            <p className="text-muted-foreground text-sm">{t("guests.noGuests")}</p>
          ) : (
            <DataTable
              columns={columns}
              data={guests}
              getRowId={(row) => String(row.id)}
              enableFilterInput
              filterInputPlaceholder={t("users.filterByHandle")}
              enablePagination
              {...table.tableProps(guestsQuery.data?.total_count ?? 0)}
            />
          )}
        </CardContent>
      </Card>

      <ExtendGuestDialog
        communityId={communityId}
        guest={extending}
        onOpenChange={(open) => !open && setExtending(null)}
      />

      <RemoveCommunityMemberDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        userId={removing?.userId ?? null}
        email={removing?.name ?? ""}
      />
    </div>
  );
};
