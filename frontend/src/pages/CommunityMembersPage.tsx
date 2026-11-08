import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import type { PaginationState } from "@tanstack/react-table";
import { IdCard, UserMinus, UserPlus, UsersRound } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserSummary } from "@/api/generated/initiativeAPI.schemas";
import { CommunityRole } from "@/api/generated/initiativeAPI.schemas";
import { InviteMembersDialog } from "@/components/communities/InviteMembersDialog";
import { MemberDisplayNameDialog } from "@/components/communities/MemberDisplayNameDialog";
import { RemoveCommunityMemberDialog } from "@/components/communities/RemoveCommunityMemberDialog";
import { ConnectionActionButtons } from "@/components/connections/ConnectionActionButtons";
import { ConnectionActionsMenu } from "@/components/connections/ConnectionActionsMenu";
import { UserHandle } from "@/components/UserHandle";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import {
  useAssignCustomRole,
  useCustomRoleHolders,
  useCustomRoles,
  useHeldSurfaces,
} from "@/hooks/useCustomRoles";
import { useDmPermissions } from "@/hooks/useDirectMessages";
import {
  deviceJSON,
  LIST,
  type ListViewSpec,
  NO_PART_VIEW,
  useListView,
  viewKey,
} from "@/hooks/useListView";
import {
  USER_SEARCH_PAGE_SIZE,
  useUpdateCommunityMembership,
  useUserSearch,
} from "@/hooks/useUsers";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { assignableCommunityRoles, isAdminRole } from "@/lib/permissions";
import { getUrlHandle, getUserDisplayName, getUserHandle } from "@/lib/userDisplay";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { DataTable } from "@/ui/data-table";
import {
  DropdownMenuItem,
  DropdownMenuPortal,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@/ui/dropdown-menu";
import type { AppColumnDef } from "@/ui/lib/table";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";
import { StatusMessage } from "@/ui/status-message";

/**
 * Everyone in this community, and a way to reach them.
 *
 * The badge on the community's banner counts people; this is where that count
 * leads. It reads the community's own roster — the same one every member picker
 * reads — rather than the people aggregate, which answers a different
 * question: who this reader may *message*. A page that dropped everybody who
 * takes no messages would be a members page missing members.
 *
 * Each row carries the same actions a person gets anywhere else, and those do
 * still follow what the server says the reader may do. So somebody who takes
 * no messages is listed like anyone else and simply offers nothing to click,
 * which is the honest shape: they are here, and they are not reachable.
 *
 * Whoever hands out invites or keeps the roster does that here too, with the
 * same invites and changes as Settings › Users, so a custom role that holds
 * only those never needs settings. A change is offered only where the server
 * would make it.
 */
/** How long typing settles before the address and the roster follow it. */
const SEARCH_SETTLES_MS = 250;
/** The custom role picker's "none", since a radio item's value is a string. */
const NO_CUSTOM_ROLE = "none";

/** Where one person's view of a community's roster is kept: its columns. */
const membersViewSpec = (communityId: number): ListViewSpec<null> => ({
  key: viewKey("members"),
  communityId,
  read: () => null,
  defaults: { filters: null, ...NO_PART_VIEW },
  carryOver: () => {
    const columns = deviceJSON("community-members-columns");
    return columns && typeof columns === "object" ? { parts: { [LIST]: { columns } } } : null;
  },
});

export const CommunityMembersPage = () => {
  const { t } = useTranslation(["communities", "settings"]);
  const { communityId } = useParams({ strict: false }) as { communityId: string };
  const { page = 1, q = "" } = useSearch({ strict: false }) as { page?: number; q?: string };
  const navigate = useNavigate();
  const { user: me } = useAuth();

  const id = Number(communityId);
  // The reader's own membership: what they have asked to be called here. A
  // grant to visit carries no name of its own to set.
  const ownEntry = useCommunities().communities.find((community) => community.id === id);
  const canNameSelf = ownEntry !== undefined && ownEntry.accessType !== "grant";
  // Who is being named: yourself, or a member whose name you keep.
  const [naming, setNaming] = useState<UserSummary | "self" | null>(null);
  const [removing, setRemoving] = useState<UserSummary | null>(null);
  const [inviting, setInviting] = useState(false);

  const held = useHeldSurfaces();
  const invites = held.writes && held.holds("invites");
  const manages = held.writes && held.holds("members");
  const { managesAdmins, gives, takesOff } = held;
  const holdsSeat = Boolean(ownEntry?.can.seat);
  // Custom roles are given by whoever keeps the roster, while the community
  // has them open. A query that is not enabled still answers from the cache,
  // which another page may have filled, so the answer is gated too.
  const givesRoles = manages && !ownEntry?.closed_surfaces?.includes("custom_roles");
  const customRoles = useCustomRoles({ enabled: givesRoles }).data;
  const roleHolders = useCustomRoleHolders({
    enabled: givesRoles && Boolean(customRoles?.length),
  }).data;
  const heldRoleIds = useMemo(
    () => new Map((roleHolders ?? []).map((holder) => [holder.user_id, holder.role_id])),
    [roleHolders]
  );
  const { mutate: assignRole } = useAssignCustomRole();
  const { mutate: changeRung } = useUpdateCommunityMembership({
    onError: (error: unknown) =>
      toast.error(getErrorMessage(error, "communities:users.failedToUpdateRole")),
  });
  const members = useUserSearch({
    search: q || undefined,
    page,
    pageSize: USER_SEARCH_PAGE_SIZE,
    communityIdOverride: id,
    // Your own row is where you set your name, so it leads the first page and
    // stays on top however the table is sorted.
    selfFirst: true,
  });
  const rows = useMemo(() => members.data?.items ?? [], [members.data]);
  // One question for the whole page. Asked per row, this is a request per row.
  const permissions = useDmPermissions(useMemo(() => rows.map((row) => row.id), [rows]));
  const total = members.data?.total_count ?? 0;
  const pageSize = members.data?.page_size ?? USER_SEARCH_PAGE_SIZE;

  /** Both the search and the page live in the address, so a roster somebody
   *  is halfway through is a link they can send. */
  const setSearch = useCallback(
    (next: Record<string, unknown>) =>
      void navigate({
        to: ".",
        search: (old: Record<string, unknown>) => ({ ...old, ...next }),
        replace: true,
      }),
    [navigate]
  );

  // The field answers every keystroke; the address and the request wait for
  // typing to stop. Committing each letter re-runs the route and asks the
  // server again, which is what made this lag behind the typing.
  const [draft, setDraft] = useState(q);
  const settled = useDebouncedValue(draft, SEARCH_SETTLES_MS);
  // Follow the URL when it changes from outside — back, forward, a shared link.
  useEffect(() => setDraft(q), [q]);
  useEffect(() => {
    // Only once typing has settled *onto the current draft*. Without that, an
    // address changed from outside -- back, forward, a link somebody sent --
    // is immediately overwritten by whatever was being typed 250ms ago, and
    // history cannot be walked.
    if (settled !== draft || settled === q) return;
    // A new search starts at the beginning: page 3 of the old one says nothing
    // about the new one.
    setSearch({ q: settled || undefined, page: undefined });
  }, [settled, draft, q, setSearch]);

  const answers = permissions.data?.permissions ?? {};

  // The columns this person shows, kept in their view of the roster. What
  // this device kept before carries over.
  const membersView = useListView(
    useMemo(() => membersViewSpec(Number(communityId)), [communityId])
  );
  const { columns: columnVisibility, setColumns: setColumnVisibility } = membersView;

  const columns = useMemo<AppColumnDef<UserSummary>[]>(
    () => [
      {
        id: "person",
        meta: { label: t("members.person") },
        header: () => <span className="font-medium">{t("members.person")}</span>,
        accessorFn: (row) => row.username,
        cell: ({ row }) => (
          <Link
            to="/u/$handle"
            params={{ handle: getUrlHandle(row.original) }}
            className="flex min-w-0 items-center gap-2 hover:underline"
          >
            <ProfileAvatar
              user={row.original}
              decorations={row.original.profile_decorations}
              className="size-7 shrink-0"
            />
            <UserHandle user={row.original} className="min-w-0" nameClassName="min-w-0 truncate" />
            {/* Only the exception is worn. Badging the other nine rows in ten
                "member" would say nothing and cost the width the actions
                need. */}
            {isAdminRole(row.original.community_role) ? (
              <Badge variant="secondary" className="shrink-0">
                {row.original.community_role === CommunityRole.superadmin
                  ? t("members.superadmin")
                  : t("members.admin")}
              </Badge>
            ) : null}
          </Link>
        ),
      },
      {
        id: "name",
        meta: { label: t("members.name") },
        header: () => <span className="font-medium">{t("members.name")}</span>,
        accessorFn: (row) => row.display_name ?? "",
        cell: ({ row }) => (
          <span className="truncate text-muted-foreground">{row.original.display_name ?? ""}</span>
        ),
      },
      {
        id: "actions",
        meta: { label: t("members.actions") },
        enableSorting: false,
        header: () => <span className="sr-only">{t("members.actions")}</span>,
        cell: ({ row }) => {
          // Your own row carries none of this: starring, ignoring and every
          // way in are refused for yourself, so offering them is offering
          // errors.
          if (row.original.id === me?.id) return null;
          const member = row.original;
          const person = {
            id: member.id,
            username: member.username,
            discriminator: member.discriminator,
          };
          // Somebody's rung, and removing them, answer to whoever may make an
          // admin when they are one, and to the seat when they hold it. A
          // guest's rung is set where guests are.
          const rung = member.community_role ?? CommunityRole.member;
          const isGuest = rung === CommunityRole.guest;
          const standsOn = isAdminRole(rung) ? "admin" : "member";
          const reaches =
            (rung !== CommunityRole.superadmin || holdsSeat) &&
            (!isAdminRole(rung) || managesAdmins);
          // A custom role is given only by somebody who could take off the
          // one they hold now.
          const heldRole = customRoles?.find((role) => role.id === heldRoleIds.get(member.id));
          const givable =
            !givesRoles || isGuest || (heldRole && !takesOff(heldRole))
              ? []
              : (customRoles ?? []).filter(gives);
          return (
            <div className="flex items-center justify-end gap-1">
              <ConnectionActionButtons
                user={person}
                permission={answers[String(person.id)] ?? null}
              />
              {/* Everything else a person can be to you — ignoring above all,
                  which a roster is the likeliest place to want. Same menu as
                  their profile and their person row, so it holds no surprise
                  and nothing has to be kept in step. */}
              <ConnectionActionsMenu
                user={person}
                omit={["profile", "message", "connect", "ask"]}
                permission={answers[String(person.id)] ?? null}
              >
                {manages ? (
                  <>
                    {reaches && managesAdmins && !isGuest ? (
                      <DropdownMenuSub>
                        <DropdownMenuSubTrigger>
                          {t("users.communityRoleColumn")}
                        </DropdownMenuSubTrigger>
                        <DropdownMenuPortal>
                          <DropdownMenuSubContent>
                            <DropdownMenuRadioGroup
                              value={rung}
                              onValueChange={(value) => {
                                if (value === rung) return;
                                changeRung({
                                  communityId: id,
                                  userId: member.id,
                                  role: value as CommunityRole,
                                });
                              }}
                            >
                              {assignableCommunityRoles(holdsSeat).map((option) => (
                                <DropdownMenuRadioItem key={option} value={option}>
                                  {t(`users.communityRole.${option}` as never)}
                                </DropdownMenuRadioItem>
                              ))}
                            </DropdownMenuRadioGroup>
                          </DropdownMenuSubContent>
                        </DropdownMenuPortal>
                      </DropdownMenuSub>
                    ) : null}
                    {givable.length > 0 ? (
                      <DropdownMenuSub>
                        <DropdownMenuSubTrigger>
                          {t("settings:customRoles.column")}
                        </DropdownMenuSubTrigger>
                        <DropdownMenuPortal>
                          <DropdownMenuSubContent>
                            <DropdownMenuRadioGroup
                              value={heldRole ? String(heldRole.id) : NO_CUSTOM_ROLE}
                              onValueChange={(value) =>
                                assignRole({
                                  userId: member.id,
                                  roleId: value === NO_CUSTOM_ROLE ? null : Number(value),
                                })
                              }
                            >
                              <DropdownMenuRadioItem value={NO_CUSTOM_ROLE}>
                                {t("settings:customRoles.none")}
                              </DropdownMenuRadioItem>
                              {givable.map((role) => (
                                <DropdownMenuRadioItem key={role.id} value={String(role.id)}>
                                  <span className="flex flex-col">
                                    <span>{role.name}</span>
                                    {/* A role applies while its holder stands on its rung. */}
                                    {role.base_rung === standsOn ? null : (
                                      <span className="text-muted-foreground text-xs">
                                        {role.base_rung === "admin"
                                          ? t("settings:customRoles.appliesWhileAdmin")
                                          : t("settings:customRoles.appliesWhileMember")}
                                      </span>
                                    )}
                                  </span>
                                </DropdownMenuRadioItem>
                              ))}
                            </DropdownMenuRadioGroup>
                          </DropdownMenuSubContent>
                        </DropdownMenuPortal>
                      </DropdownMenuSub>
                    ) : null}
                    <DropdownMenuItem onSelect={() => setNaming(member)}>
                      <IdCard className="h-4 w-4" />
                      {t("displayName.adminAction")}
                    </DropdownMenuItem>
                    {reaches ? (
                      <DropdownMenuItem
                        className="text-destructive"
                        onSelect={() => setRemoving(member)}
                      >
                        <UserMinus className="h-4 w-4" />
                        {t("users.removeFromCommunity")}
                      </DropdownMenuItem>
                    ) : null}
                  </>
                ) : null}
              </ConnectionActionsMenu>
            </div>
          );
        },
      },
    ],
    [
      t,
      me?.id,
      answers,
      id,
      manages,
      givesRoles,
      managesAdmins,
      gives,
      takesOff,
      holdsSeat,
      customRoles,
      heldRoleIds,
      assignRole,
      changeRung,
    ]
  );

  return (
    <div className="space-y-6">
      {/* Your own name sits up here rather than on your row, which in a big
          community may be several pages in. */}
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="font-semibold text-3xl tracking-tight">{t("members.title")}</h1>
          <p className="text-muted-foreground text-sm">{t("memberCount", { count: total })}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {invites ? (
            <Button variant="outline" size="sm" onClick={() => setInviting(true)}>
              <UserPlus className="h-4 w-4" />
              {t("inviteMembers")}
            </Button>
          ) : null}
          {canNameSelf ? (
            <Button variant="outline" size="sm" onClick={() => setNaming("self")}>
              <IdCard className="h-4 w-4" />
              {t("displayName.menuItem")}
            </Button>
          ) : null}
        </div>
      </header>

      {members.isError ? (
        <StatusMessage
          icon={<UsersRound className="size-6" aria-hidden />}
          title={t("members.failed")}
        />
      ) : (
        <DataTable
          columns={columns}
          data={rows}
          // Controlled, because the roster is searched on the server: the
          // table's own filter would only narrow the page already on screen,
          // which is the wrong answer for everybody past the first twenty-five.
          enableFilterInput
          filterInputPlaceholder={t("members.searchPlaceholder")}
          filterValue={draft}
          onFilterValueChange={setDraft}
          enableColumnVisibilityDropdown
          columnVisibility={columnVisibility}
          onColumnVisibilityChange={setColumnVisibility}
          enablePagination
          manualPagination
          pageCount={Math.max(1, Math.ceil(total / pageSize))}
          rowCount={total}
          pageIndex={page - 1}
          onPaginationChange={(next: PaginationState) =>
            setSearch({ page: next.pageIndex + 1 === 1 ? undefined : next.pageIndex + 1 })
          }
          getRowId={(row: UserSummary) => String(row.id)}
          pinnedRowId={me ? String(me.id) : undefined}
        />
      )}

      <MemberDisplayNameDialog
        communityId={id}
        member={
          naming && naming !== "self" ? { id: naming.id, name: getUserHandle(naming) } : undefined
        }
        current={naming === "self" ? ownEntry?.display_name : naming?.display_name}
        open={naming !== null}
        onOpenChange={(open) => !open && setNaming(null)}
      />
      <RemoveCommunityMemberDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        userId={removing?.id ?? null}
        email={removing ? getUserDisplayName(removing) : ""}
      />
      {inviting ? <InviteMembersDialog open onOpenChange={setInviting} /> : null}
    </div>
  );
};
