import { Link } from "@tanstack/react-router";
import {
  Archive,
  ArchiveRestore,
  ChevronsUpDown,
  CircleAlert,
  Loader2,
  Settings,
  Trash2,
  UserPlus,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeRead } from "@/api/generated/initiativeAPI.schemas";
import { DeleteInitiativeDialog } from "@/components/initiatives/DeleteInitiativeDialog";
import { POLICY_LABEL_KEY } from "@/components/initiatives/JoinPolicySection";
import { type MemberLike, useSeenMembers } from "@/components/members/MemberSearchSelect";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { useArchiveEntity, useUnarchiveEntity } from "@/hooks/useArchive";
import { useCommunities } from "@/hooks/useCommunities";
import { useHeldSurfaces } from "@/hooks/useCustomRoles";
import { useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import {
  useAddInitiativeMember,
  useCommunityInitiatives,
  useDeleteInitiative,
  useInitiativeManagers,
  useRemoveInitiativeMember,
  useUpdateInitiativeMember,
} from "@/hooks/useInitiatives";
import { type MemberSearchScope, useUserSearch } from "@/hooks/useUsers";
import { useCommunityPath } from "@/lib/communityUrl";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { toast } from "@/lib/mascotToast";
import { isAdminRole } from "@/lib/permissions";
import { initiativeRoute } from "@/lib/tools";
import { getUserDisplayName } from "@/lib/userDisplay";
import { Button } from "@/ui/button";
import { Combobox } from "@/ui/combobox";
import { DataTable } from "@/ui/data-table";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/ui/dropdown-menu";
import { listFormat } from "@/ui/lib/intl";
import type { AppColumnDef } from "@/ui/lib/table";
import { SkeletonRegion, TableSkeleton } from "@/ui/page-skeletons";
import { RowActionsMenu } from "@/ui/row-actions-menu";
import { Skeleton } from "@/ui/skeleton";
import { StatusMessage } from "@/ui/status-message";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

import { CommunityInitiativeDefaultsCard } from "./CommunityInitiativeDefaultsCard";

const COMMUNITY_SCOPE: MemberSearchScope = { type: "community" };
const NONE: never[] = [];

/**
 * Per-row project-manager picker — how a community admin staffs an initiative, and
 * how they put one in their own sidebar (tick yourself).
 *
 * Ticking someone promotes them: an existing member's role changes, a
 * non-member gets a membership row. Unticking only takes the manager role away
 * — they stay in the initiative with the built-in member role. A community admin is
 * the exception: they cannot hold a standard role, so unticking removes their
 * row (which is also how they leave an initiative they added themselves to).
 */
const InitiativeManagersCell = ({ initiative }: { initiative: InitiativeRead }) => {
  const { t, i18n } = useTranslation(["initiatives", "common"]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rolesQuery = useInitiativeRoles(initiative.id);
  const managersQuery = useInitiativeManagers(initiative.id);

  // Candidates are the community's members matching what was typed, asked of the
  // server once the picker is open.
  const searchQuery = useUserSearch({ search: query, enabled: open });
  const results = useMemo(
    () => (searchQuery.data?.items ?? []).filter((candidate) => candidate.status !== "anonymized"),
    [searchQuery.data]
  );

  // The project manager by name first: moderator is a manager role too, and
  // this column staffs an initiative rather than hands out Full access.
  const managerRole = useMemo(
    () =>
      rolesQuery.data?.find((role) => role.name === "project_manager") ??
      rolesQuery.data?.find((role) => role.is_manager),
    [rolesQuery.data]
  );
  const memberRole = useMemo(
    () => rolesQuery.data?.find((role) => role.name === "member"),
    [rolesQuery.data]
  );

  // The current managers lead the list whatever was typed, so each can be
  // unticked. What unticking does depends on whether they are a community admin,
  // which the community answers by id.
  const managers = useMemo<MemberLike[]>(
    () => (managersQuery.data ?? []).map((m) => m.user),
    [managersQuery.data]
  );
  const managerIds = useMemo(() => new Set(managers.map((m) => m.id)), [managers]);
  const managerCount = managers.length;
  const managerIdList = useMemo(() => [...managerIds], [managerIds]);
  const knownManagers = useSeenMembers(
    COMMUNITY_SCOPE,
    open ? managerIdList : NONE,
    undefined,
    results
  );
  const candidates = useMemo<MemberLike[]>(
    () => [
      ...managers.map((manager) => knownManagers.get(manager.id) ?? manager),
      ...results.filter((candidate) => !managerIds.has(candidate.id)),
    ],
    [managers, knownManagers, results, managerIds]
  );

  const onSuccess = () => {
    toast.success(t("manage.managersUpdated"));
  };
  const managersError = "initiatives:manage.managersError";
  const addMember = useAddInitiativeMember({ onSuccess }, managersError);
  const updateMember = useUpdateInitiativeMember({ onSuccess }, managersError);
  const removeMember = useRemoveInitiativeMember({ onSuccess }, managersError);
  const pending = addMember.isPending || updateMember.isPending || removeMember.isPending;

  const toggle = (userId: number) => {
    if (!managerRole) {
      return;
    }
    if (!managerIds.has(userId)) {
      // Adding someone who is already a member moves them onto the role.
      addMember.mutate({
        initiativeId: initiative.id,
        data: { user_id: userId, role_id: managerRole.id },
      });
      return;
    }
    if (isAdminRole(knownManagers.get(userId)?.community_role) || !memberRole) {
      removeMember.mutate({ initiativeId: initiative.id, userId });
    } else {
      updateMember.mutate({
        initiativeId: initiative.id,
        userId,
        data: { role_id: memberRole.id },
      });
    }
  };

  if (rolesQuery.isLoading || managersQuery.isLoading) {
    return <Skeleton className="h-9 w-36" />;
  }

  // An unusable picker must say so rather than sit on a spinner that never
  // resolves.
  if (rolesQuery.isError || managersQuery.isError || !managerRole) {
    return (
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="inline-flex text-destructive">
              <CircleAlert className="h-4 w-4" />
            </span>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs">{t("manage.managersUnavailable")}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  // The managers by name: who runs it is the question this column answers.
  const shown = managers.map((manager) => knownManagers.get(manager.id) ?? manager);
  const selectedLabel =
    managerCount === 0
      ? t("manage.noManagers")
      : listFormat(i18n.language).format(shown.map((manager) => getUserDisplayName(manager)));

  return (
    <Combobox
      multiple
      items={candidates.map((candidate) => ({
        value: String(candidate.id),
        label: getUserDisplayName(candidate),
        // Unticking waits until the community has said whether this manager is
        // one of its admins.
        disabled: pending || (managerIds.has(candidate.id) && !knownManagers.has(candidate.id)),
      }))}
      value={managerIdList.map(String)}
      // One row is ticked or unticked at a time: the one in only one list.
      onValueChange={(next) => {
        const changed = [...next, ...managerIdList.map(String)].find(
          (value) => next.includes(value) !== managerIds.has(Number(value))
        );
        if (changed) toggle(Number(changed));
      }}
      onSearchChange={setQuery}
      onOpenChange={setOpen}
      loading={searchQuery.isFetching && candidates.length === 0}
      searchPlaceholder={t("common:search")}
      emptyMessage={t("manage.noCandidates")}
      trigger={
        <Button
          variant="outline"
          size="sm"
          role="combobox"
          aria-label={t("manage.managersColumn")}
          className={
            managerCount === 0
              ? "max-w-48 justify-between border-dashed font-normal text-muted-foreground"
              : "max-w-48 justify-between font-normal"
          }
        >
          {managerCount === 0 ? (
            <UserPlus className="h-4 w-4 shrink-0" />
          ) : (
            <span className="flex shrink-0 -space-x-1.5">
              {shown.slice(0, 3).map((manager) => (
                <ProfileAvatar
                  key={manager.id}
                  user={manager}
                  className="h-5 w-5 ring-2 ring-background"
                />
              ))}
            </span>
          )}
          <span className="min-w-0 truncate">{selectedLabel}</span>
          {pending ? (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
          ) : (
            <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
          )}
        </Button>
      }
    />
  );
};

export const InitiativesPage = () => {
  const { t } = useTranslation(["initiatives", "common"]);
  const { activeCommunity } = useCommunities();
  const gp = useCommunityPath();
  // Whoever holds the community's initiatives, not only its admins.
  const managesInitiatives = useHeldSurfaces().holds("initiatives");
  // What every initiative uses is the admin rung's own to set.
  const isCommunityAdmin = Boolean(activeCommunity?.can.administer);

  // The community-wide listing, not the admin's own memberships — this table is
  // where they manage initiatives they have not joined.
  const initiativesQuery = useCommunityInitiatives({ enabled: managesInitiatives });
  const deleteInitiative = useDeleteInitiative();
  const archiveInitiative = useArchiveEntity();
  const unarchiveInitiative = useUnarchiveEntity();

  const [deleteTarget, setDeleteTarget] = useState<InitiativeRead | null>(null);
  // Archived initiatives are a view of their own, as every tool's are.
  const [view, setView] = useState<"active" | "archived">("active");

  const toggleArchive = (initiative: InitiativeRead) => {
    const nextArchived = initiative.archived_at === null;
    const mutation = nextArchived ? archiveInitiative : unarchiveInitiative;
    mutation.mutate(
      { entityType: "initiative", entityId: initiative.id },
      {
        onSuccess: () => {
          toast.success(
            nextArchived
              ? t("manage.archivedToast", { name: initiative.name })
              : t("manage.unarchivedToast", { name: initiative.name })
          );
        },
      }
    );
  };

  const confirmDelete = () => {
    if (!deleteTarget) return;
    deleteInitiative.mutate(deleteTarget.id, {
      onSuccess: () => {
        toast.success(t("manage.deletedToast", { name: deleteTarget.name }));
        setDeleteTarget(null);
      },
    });
  };

  const columns: AppColumnDef<InitiativeRead>[] = [
    {
      accessorKey: "name",
      header: t("manage.nameColumn"),
      cell: ({ row }) => {
        const initiative = row.original;
        return (
          <div className="flex min-w-0 items-start gap-2.5">
            <InitiativeColorDot color={initiative.color} className="mt-1.5 shrink-0" />
            <div className="min-w-0">
              <Link
                to={gp(`${initiativeRoute(initiative.id)}/settings`)}
                className="font-medium hover:underline"
              >
                {initiative.name}
              </Link>
              <div className="flex flex-wrap gap-x-3 text-muted-foreground text-xs">
                <span>{t(POLICY_LABEL_KEY[initiative.join_policy] as never)}</span>
                <Link
                  to={gp(`${initiativeRoute(initiative.id)}/settings/members`)}
                  className="hover:underline"
                >
                  {t("manage.memberCount", { count: initiative.member_count })}
                </Link>
                <span className="font-mono">#{initiative.id}</span>
              </div>
            </div>
          </div>
        );
      },
    },
    {
      id: "managers",
      header: t("manage.managersColumn"),
      cell: ({ row }) => <InitiativeManagersCell initiative={row.original} />,
    },
    {
      id: "actions",
      header: () => <span className="sr-only">{t("manage.actionsColumn")}</span>,
      cell: ({ row }) => {
        const initiative = row.original;
        const archived = initiative.archived_at !== null;
        return (
          <RowActionsMenu subject={initiative.name}>
            {!archived && (
              <DropdownMenuItem asChild>
                <Link to={gp(`${initiativeRoute(initiative.id)}/settings`)}>
                  <Settings className="h-4 w-4" />
                  {t("manage.openSettings")}
                </Link>
              </DropdownMenuItem>
            )}
            <DropdownMenuItem
              disabled={archiveInitiative.isPending || unarchiveInitiative.isPending}
              onSelect={() => toggleArchive(initiative)}
            >
              {archived ? <ArchiveRestore className="h-4 w-4" /> : <Archive className="h-4 w-4" />}
              {archived ? t("manage.unarchive") : t("manage.archive")}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              onSelect={() => setDeleteTarget(initiative)}
            >
              <Trash2 className="h-4 w-4" />
              {t("manage.delete")}
            </DropdownMenuItem>
          </RowActionsMenu>
        );
      },
    },
  ];

  if (!managesInitiatives) {
    return <p className="text-muted-foreground text-sm">{t("manage.adminRequired")}</p>;
  }

  if (initiativesQuery.isLoading) {
    return (
      <SkeletonRegion>
        <TableSkeleton rows={5} columns={4} />
      </SkeletonRegion>
    );
  }

  if (initiativesQuery.isError || !initiativesQuery.data) {
    return <StatusMessage onRetry={initiativesQuery.refetch} />;
  }

  const live = initiativesQuery.data.filter((initiative) => initiative.archived_at === null);
  const archived = initiativesQuery.data.filter((initiative) => initiative.archived_at !== null);
  const counts = { active: live.length, archived: archived.length };

  return (
    <div className="space-y-6">
      <SettingsSection description={t("manage.description")}>
        <ToggleGroup
          type="single"
          value={view}
          // Radix clears a single-select group when its item is clicked
          // again; the table always shows one of the two.
          onValueChange={(next) => next && setView(next as "active" | "archived")}
          aria-label={t("common:toolViewFilter.label")}
          className="justify-start"
        >
          {(["active", "archived"] as const).map((option) => (
            <ToggleGroupItem key={option} value={option} className="h-9 gap-2 px-3">
              {option === "archived" && <Archive className="h-4 w-4" />}
              {t(`common:toolViewFilter.${option}`)}
              <span className="text-muted-foreground text-xs tabular-nums">{counts[option]}</span>
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <DataTable
          columns={columns}
          data={view === "active" ? live : archived}
          enableFilterInput
          filterInputColumnKey="name"
          filterInputPlaceholder={t("manage.filterByName")}
          enableResetSorting
          enablePagination
        />
      </SettingsSection>

      {isCommunityAdmin && <CommunityInitiativeDefaultsCard initiatives={live} />}

      <DeleteInitiativeDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        initiativeName={deleteTarget?.name ?? ""}
        isDeleting={deleteInitiative.isPending}
        onConfirm={confirmDelete}
      />
    </div>
  );
};
