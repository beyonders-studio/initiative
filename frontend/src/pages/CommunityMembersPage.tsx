import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import type { PaginationState } from "@tanstack/react-table";
import { IdCard, UsersRound } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserSummary } from "@/api/generated/initiativeAPI.schemas";
import { CommunityRole } from "@/api/generated/initiativeAPI.schemas";
import { MemberDisplayNameDialog } from "@/components/communities/MemberDisplayNameDialog";
import { ConnectionActionButtons } from "@/components/connections/ConnectionActionButtons";
import { ConnectionActionsMenu } from "@/components/connections/ConnectionActionsMenu";
import { StatusMessage } from "@/components/StatusMessage";
import { UserHandle } from "@/components/UserHandle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useDmPermissions } from "@/hooks/useDirectMessages";
import {
  deviceJSON,
  LIST,
  type ListViewSpec,
  NO_PART_VIEW,
  useListView,
  viewKey,
} from "@/hooks/useListView";
import { USER_SEARCH_PAGE_SIZE, useUserSearch } from "@/hooks/useUsers";
import { isAdminRole } from "@/lib/permissions";
import type { AppColumnDef } from "@/lib/table";
import { getUrlHandle } from "@/lib/userDisplay";

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
 */
/** How long typing settles before the address and the roster follow it. */
const SEARCH_SETTLES_MS = 250;

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
  const { t } = useTranslation("communities");
  const { communityId } = useParams({ strict: false }) as { communityId: string };
  const { page = 1, q = "" } = useSearch({ strict: false }) as { page?: number; q?: string };
  const navigate = useNavigate();
  const { user: me } = useAuth();

  const id = Number(communityId);
  // The reader's own membership: what they have asked to be called here. A
  // grant to visit carries no name of its own to set.
  const ownEntry = useCommunities().communities.find((community) => community.id === id);
  const canNameSelf = ownEntry !== undefined && ownEntry.accessType !== "grant";
  const [namingSelf, setNamingSelf] = useState(false);
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
          const person = {
            id: row.original.id,
            username: row.original.username,
            discriminator: row.original.discriminator,
          };
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
              />
            </div>
          );
        },
      },
    ],
    [t, me?.id, answers]
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
        {canNameSelf ? (
          <Button variant="outline" size="sm" onClick={() => setNamingSelf(true)}>
            <IdCard className="h-4 w-4" />
            {t("displayName.menuItem")}
          </Button>
        ) : null}
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
        current={ownEntry?.display_name}
        open={namingSelf}
        onOpenChange={setNamingSelf}
      />
    </div>
  );
};
