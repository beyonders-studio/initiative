import { Download } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  ListAllUsersSortBy,
  type OperatorUserRead,
  type UserRole,
} from "@/api/generated/initiativeAPI.schemas";
import {
  sheetOffersSomething,
  UserOperatorSettingsSheet,
} from "@/components/platform/UserOperatorSettingsSheet";
import { UserHandle } from "@/components/UserHandle";
import { useAuth } from "@/hooks/useAuth";
import { useExportPlatformUsersCsv, usePlatformUsers } from "@/hooks/useOperatorUsers";
import { useServerTableState } from "@/hooks/useServerTableState";
import { getErrorMessage } from "@/lib/errorMessage";
import { formatDate, formatDateTime } from "@/lib/formatDate";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";
import { getUserHandle } from "@/lib/userDisplay";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Card, CardContent, CardHeader } from "@/ui/card";
import { DataTable } from "@/ui/data-table";
import { DropdownMenuItem } from "@/ui/dropdown-menu";
import type { AppColumnDef } from "@/ui/lib/table";
import { SkeletonRegion, TableSkeleton } from "@/ui/page-skeletons";
import { RowActionsMenu } from "@/ui/row-actions-menu";
import { SortHeader } from "@/ui/sort-icon";

/** The columns the server sorts the roster by. Status sorts by how much of the
 *  app is left to an account, which brings the ones needing attention together
 *  at one end. */
const SORT_FIELDS = Object.values(ListAllUsersSortBy);

export const SettingsPlatformUsersPage = () => {
  const { t } = useTranslation(["settings", "common"]);
  const { user } = useAuth();
  const [managingId, setManagingId] = useState<number | null>(null);

  // Viewing the roster needs ``users.read`` (support+). What the viewer may do
  // to each account comes with its row, in `allowed_actions`: the server asks
  // their capabilities, their rung, the account's state and how this
  // deployment signs in, so nothing here asks again.
  const canView = hasCapability(user, Capability.usersRead);
  // The role select offers nothing above the viewer's own rung.
  const actorRole = (user?.role ?? "member") as UserRole;

  // Searched, sorted and paged on the server: the roster is every account on
  // the deployment, so the table only ever holds the page on screen.
  const table = useServerTableState(SORT_FIELDS);
  const usersQuery = usePlatformUsers(table.params, { enabled: canView });
  const rows = usersQuery.data?.items ?? [];
  const totalCount = usersQuery.data?.total_count ?? 0;

  // Read the row back out of the query, so a save re-renders the sheet with
  // what was actually persisted.
  const managing = rows.find((row) => row.id === managingId) ?? null;

  const exportPlatformUsers = useExportPlatformUsersCsv({
    onError: (err) => {
      toast.error(getErrorMessage(err, "settings:platformUsers.exportError"));
    },
  });

  const exportUserCsv = (platformUser: OperatorUserRead) => {
    // Named by handle. The address never arrives here in full any more, and a
    // filename outlives the download — in a directory listing, in whatever it
    // gets mailed on to.
    const safeHandle = platformUser.username.replace(/[^a-zA-Z0-9._-]+/g, "_");
    exportPlatformUsers.mutate({
      params: { user_id: [platformUser.id] },
      filename: `user-${platformUser.id}-${safeHandle}.csv`,
    });
  };

  const exportAllUsersCsv = () => {
    const datestamp = new Date().toISOString().slice(0, 10);
    exportPlatformUsers.mutate({
      params: {},
      filename: `platform-users-${datestamp}.csv`,
    });
  };

  if (!canView) {
    return <p className="text-muted-foreground text-sm">{t("platformUsers.permissionRequired")}</p>;
  }

  if (usersQuery.isLoading) {
    return (
      <SkeletonRegion label={t("platformUsers.loading")}>
        <TableSkeleton rows={8} columns={5} />
      </SkeletonRegion>
    );
  }

  if (usersQuery.isError || !usersQuery.data) {
    return <p className="text-destructive text-sm">{t("platformUsers.loadError")}</p>;
  }

  const userColumns: AppColumnDef<OperatorUserRead>[] = [
    {
      accessorKey: "id",
      header: ({ column }) => <SortHeader column={column} label={t("platformUsers.columnId")} />,
      cell: ({ row }) => (
        <p className="font-mono text-muted-foreground text-sm">{row.original.id}</p>
      ),
      // The id counts up as accounts are made, so sorting it is sorting by
      // when somebody joined — which is why there is no separate date column.
      enableSorting: true,
    },
    {
      id: "username",
      accessorFn: (row) => getUserHandle(row),
      header: ({ column }) => (
        <SortHeader column={column} label={t("platformUsers.columnHandle")} />
      ),
      // The handle is the whole of the identification here. An account's real
      // name is its own to give out, and an operator does not need it to do
      // any of this.
      cell: ({ row }) => <UserHandle user={row.original} className="text-sm" />,
      enableSorting: true,
    },
    {
      id: "status",
      accessorFn: (row) => row.status,
      header: ({ column }) => (
        <SortHeader column={column} label={t("platformUsers.columnStatus")} />
      ),
      enableSorting: true,
      cell: ({ row }) => {
        const platformUser = row.original;
        // A deleted account is the one status with a date attached and a way
        // back, so it is a tag rather than a word — the same tag a deleted
        // community carries in the Communities table.
        if (platformUser.status === "deleted") {
          return (
            <div className="space-y-0.5">
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge variant="destructive">{t("platformUsers.deleted")}</Badge>
                {platformUser.open_case_count > 0 && (
                  <Badge variant="outline">
                    {t("platformUsers.openCases", { count: platformUser.open_case_count })}
                  </Badge>
                )}
              </div>
              {platformUser.purge_at ? (
                <p className="text-muted-foreground text-xs">
                  {t("platformUsers.erasedOn", {
                    date: formatDate(platformUser.purge_at),
                  })}
                </p>
              ) : (
                <p className="text-muted-foreground text-xs">{t("platformUsers.erasedNever")}</p>
              )}
            </div>
          );
        }
        const labelKey =
          platformUser.status === "active"
            ? "platformUsers.active"
            : platformUser.status === "anonymized"
              ? "platformUsers.anonymized"
              : platformUser.status === "suspended"
                ? "platformUsers.suspended"
                : "platformUsers.deactivated";
        const className =
          platformUser.status === "active"
            ? "text-sm text-green-600 dark:text-green-400"
            : "text-muted-foreground text-sm";
        return (
          <div className="space-y-0.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className={className}>{t(labelKey)}</span>
              {platformUser.open_case_count > 0 && (
                <Badge variant="outline">
                  {t("platformUsers.openCases", { count: platformUser.open_case_count })}
                </Badge>
              )}
            </div>
            {platformUser.sign_in_locked_until && (
              <div>
                <Badge variant="outline">{t("platformUsers.signInLocked")}</Badge>
                <p className="text-muted-foreground text-xs">
                  {t("platformUsers.signInLockedUntil", {
                    time: formatDateTime(platformUser.sign_in_locked_until),
                  })}
                </p>
              </div>
            )}
          </div>
        );
      },
    },
    {
      id: "manage",
      header: "",
      enableSorting: false,
      cell: ({ row }) => {
        const platformUser = row.original;
        // Nothing to open where the sheet would offer this viewer nothing for
        // this account.
        if (!sheetOffersSomething(platformUser)) return null;
        return (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setManagingId(platformUser.id)}
            aria-label={t("platformUsers.sheet.openLabel", {
              handle: getUserHandle(platformUser),
            })}
          >
            {t("platformUsers.sheet.open")}
          </Button>
        );
      },
    },
    {
      id: "actions",
      header: t("platformUsers.columnActions"),
      enableSorting: false,
      cell: ({ row }) => {
        const platformUser = row.original;
        // Every act on the account is in its sheet, where the case it is for
        // can be named; what is left here acts on nothing.
        return (
          <RowActionsMenu subject={getUserHandle(platformUser)}>
            <DropdownMenuItem onSelect={() => exportUserCsv(platformUser)}>
              <Download className="h-4 w-4" />
              {t("platformUsers.exportUser")}
            </DropdownMenuItem>
          </RowActionsMenu>
        );
      },
    },
  ];

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-row justify-end">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={exportAllUsersCsv}
            disabled={!totalCount}
          >
            <Download className="h-4 w-4" />
            {t("platformUsers.exportAll")}
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <DataTable
            columns={userColumns}
            data={rows}
            getRowId={(row) => String(row.id)}
            enableFilterInput
            filterInputPlaceholder={t("platformUsers.filterPlaceholder")}
            enableResetSorting
            enablePagination
            {...table.tableProps(totalCount)}
          />
        </CardContent>

        <UserOperatorSettingsSheet
          user={managing}
          open={managing !== null}
          onOpenChange={(next) => {
            if (!next) setManagingId(null);
          }}
          actorRole={actorRole}
        />
      </Card>
    </div>
  );
};
