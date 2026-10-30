import {
  Archive,
  ArchiveRestore,
  Check,
  ChevronsUpDown,
  CircleAlert,
  Loader2,
  Trash2,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeRead } from "@/api/generated/initiativeAPI.schemas";
import { CommunityInitiativeDefaultsCard } from "@/components/initiatives/CommunityInitiativeDefaultsCard";
import { DeleteInitiativeDialog } from "@/components/initiatives/DeleteInitiativeDialog";
import { type MemberLike, useSeenMembers } from "@/components/members/MemberSearchSelect";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { DataTable } from "@/components/ui/data-table";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useArchiveEntity, useUnarchiveEntity } from "@/hooks/useArchive";
import { useCommunities } from "@/hooks/useCommunities";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
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
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { isAdminRole } from "@/lib/permissions";
import type { AppColumnDef } from "@/lib/table";
import { getUserDisplayName } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

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
  const { t } = useTranslation(["initiatives", "common"]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebouncedValue(query, 250);
  const rolesQuery = useInitiativeRoles(initiative.id);
  const managersQuery = useInitiativeManagers(initiative.id);

  // Candidates are the community's members matching what was typed, asked of the
  // server once the picker is open.
  const searchQuery = useUserSearch({ search: debouncedQuery, enabled: open });
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

  const onError = (error: unknown) => {
    toast.error(getErrorMessage(error, "initiatives:manage.managersError"));
  };
  const onSuccess = () => {
    toast.success(t("manage.managersUpdated"));
  };
  const addMember = useAddInitiativeMember({ onSuccess, onError });
  const updateMember = useUpdateInitiativeMember({ onSuccess, onError });
  const removeMember = useRemoveInitiativeMember({ onSuccess, onError });
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

  const selectedLabel =
    managerCount === 0
      ? t("manage.noManagers")
      : managerCount === 1
        ? getUserDisplayName(managers[0], t("manage.managerCount", { count: 1 }))
        : t("manage.managerCount", { count: managerCount });

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setQuery("");
      }}
    >
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          role="combobox"
          aria-expanded={open}
          aria-label={t("manage.managersColumn")}
          className="w-48 justify-between font-normal"
        >
          <span className={managerCount === 0 ? "text-muted-foreground" : undefined}>
            {selectedLabel}
          </span>
          {pending ? (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
          ) : (
            <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[280px] p-0">
        <Command shouldFilter={false}>
          <CommandInput placeholder={t("common:search")} value={query} onValueChange={setQuery} />
          <CommandList>
            {searchQuery.isFetching && candidates.length === 0 ? (
              <div className="flex items-center justify-center gap-2 py-6 text-muted-foreground text-sm">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t("common:loading")}
              </div>
            ) : (
              <CommandEmpty>{t("manage.noCandidates")}</CommandEmpty>
            )}
            <CommandGroup className="max-h-64 overflow-y-auto">
              {candidates.map((candidate) => {
                const isManager = managerIds.has(candidate.id);
                return (
                  <CommandItem
                    key={candidate.id}
                    value={String(candidate.id)}
                    // Unticking waits until the community has said whether this
                    // manager is one of its admins.
                    disabled={pending || (isManager && !knownManagers.has(candidate.id))}
                    onSelect={() => toggle(candidate.id)}
                  >
                    <Check className={cn("h-4 w-4", isManager ? "opacity-100" : "opacity-0")} />
                    {getUserDisplayName(candidate)}
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
};

export const SettingsInitiativesPage = () => {
  const { t } = useTranslation(["initiatives", "common"]);
  const { activeCommunity } = useCommunities();
  const isCommunityAdmin = Boolean(activeCommunity?.can.administer);

  // The community-wide listing, not the admin's own memberships — this table is
  // where they manage initiatives they have not joined.
  const initiativesQuery = useCommunityInitiatives({ enabled: isCommunityAdmin });
  const deleteInitiative = useDeleteInitiative();
  const archiveInitiative = useArchiveEntity();
  const unarchiveInitiative = useUnarchiveEntity();

  const [deleteTarget, setDeleteTarget] = useState<InitiativeRead | null>(null);

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
      accessorKey: "id",
      header: t("manage.idColumn"),
      cell: ({ row }) => (
        <span className="font-mono text-muted-foreground text-sm">{row.original.id}</span>
      ),
    },
    {
      accessorKey: "name",
      header: t("manage.nameColumn"),
      cell: ({ row }) => {
        const initiative = row.original;
        return (
          <div className="flex items-center gap-2">
            {initiative.color ? (
              <span
                className="inline-block h-3 w-3 shrink-0 rounded-full"
                style={{ backgroundColor: initiative.color }}
                aria-hidden
              />
            ) : null}
            <span className="font-medium">{initiative.name}</span>
          </div>
        );
      },
    },
    {
      id: "members",
      header: t("manage.membersColumn"),
      cell: ({ row }) => (
        <span className="text-muted-foreground text-sm">
          {t("manage.memberCount", { count: row.original.member_count })}
        </span>
      ),
    },
    {
      id: "managers",
      header: t("manage.managersColumn"),
      cell: ({ row }) => <InitiativeManagersCell initiative={row.original} />,
    },
    {
      id: "status",
      header: t("manage.statusColumn"),
      cell: ({ row }) =>
        row.original.archived_at !== null ? (
          <Badge variant="outline" className="text-xs">
            {t("manage.archived")}
          </Badge>
        ) : (
          <Badge className="text-xs">{t("manage.active")}</Badge>
        ),
    },
    {
      id: "actions",
      header: t("manage.actionsColumn"),
      cell: ({ row }) => {
        const initiative = row.original;
        return (
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => toggleArchive(initiative)}
              disabled={archiveInitiative.isPending || unarchiveInitiative.isPending}
            >
              {initiative.archived_at !== null ? (
                <>
                  <ArchiveRestore className="h-4 w-4" />
                  {t("manage.unarchive")}
                </>
              ) : (
                <>
                  <Archive className="h-4 w-4" />
                  {t("manage.archive")}
                </>
              )}
            </Button>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              onClick={() => setDeleteTarget(initiative)}
            >
              <Trash2 className="h-4 w-4" />
              {t("manage.delete")}
            </Button>
          </div>
        );
      },
    },
  ];

  if (!isCommunityAdmin) {
    return <p className="text-muted-foreground text-sm">{t("manage.adminRequired")}</p>;
  }

  if (initiativesQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">{t("manage.loading")}</p>;
  }

  if (initiativesQuery.isError || !initiativesQuery.data) {
    return <p className="text-destructive text-sm">{t("manage.loadError")}</p>;
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardDescription>{t("manage.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <DataTable
            columns={columns}
            data={initiativesQuery.data}
            enableFilterInput
            filterInputColumnKey="name"
            filterInputPlaceholder={t("manage.filterByName")}
            enableResetSorting
            enablePagination
          />
        </CardContent>
      </Card>

      {isCommunityAdmin && <CommunityInitiativeDefaultsCard />}

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
