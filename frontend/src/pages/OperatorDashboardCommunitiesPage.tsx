import { Link } from "@tanstack/react-router";
import { KeyRound, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  CommunityAction,
  CommunityStatus,
  ListPlatformCommunityStorageSortBy,
  type PlatformCommunityStorageRead,
} from "@/api/generated/initiativeAPI.schemas";
import { BillingConsoleButton } from "@/components/platform/BillingConsoleButton";
import { CommunityOperatorSettingsSheet } from "@/components/platform/CommunityOperatorSettingsSheet";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useServerTableState } from "@/hooks/useServerTableState";
import {
  usePlatformCommunities,
  useSetCommunitySuspension,
  useUpdateCommunityStorage,
} from "@/hooks/useSettings";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { DataTable } from "@/ui/data-table";
import { DropdownMenuItem } from "@/ui/dropdown-menu";
import type { AppColumnDef } from "@/ui/lib/table";
import { SkeletonRegion, TableSkeleton } from "@/ui/page-skeletons";
import { RowActionsMenu } from "@/ui/row-actions-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

// Storage caps are entered in binary GB (GiB) so a value round-trips cleanly
// with `formatBytes` (which is also 1024-based). The editor for them, and for
// every other operator setting, lives in CommunityOperatorSettingsSheet, and so
// does the way into the billing operator console.
const CommunityBillingCell = ({ community }: { community: PlatformCommunityStorageRead }) => {
  const { t } = useTranslation("settings");
  if (!community.allowed_actions.includes(CommunityAction.billing_support)) return null;
  return (
    <BillingConsoleButton
      community={community}
      console="support"
      size="sm"
      variant="outline"
      aria-label={t("communities.billing.openLabel", { name: community.name })}
    >
      {community.tier_name ?? t("communities.billing.noPlan")}
    </BillingConsoleButton>
  );
};

/**
 * Lifecycle-status control for one community. Changing to `suspended` or
 * `on_hold` (everyone in it loses all access) is gated behind a confirm
 * dialog; the lighter transitions apply immediately. The change saves via the same platform-communities mutation
 * and the list invalidates on success, so the Select reflects the persisted
 * status.
 *
 * The choices are the row's own `status_choices`, which the server works out:
 * every settable status on a deployment that sets plans by hand, and only a
 * suspension (and lifting it, back to the status billing last set) where
 * billing sets them.
 *
 * A deleted community has no control at all — it shows a tag instead. Deleted
 * is not a status you set: it is reached by deleting the community and left by
 * restoring it, both of which do more than move this field, so the only way
 * back is the wizard under Manage.
 *
 * A reader the row does not let set the status (`set_status`) sees it as a
 * tag too.
 */
const CommunityStatusCell = ({ community }: { community: PlatformCommunityStorageRead }) => {
  const { t } = useTranslation(["settings", "common"]);
  // Suspending and putting on hold both take everyone out of the community,
  // so each is confirmed before it is applied.
  const [pending, setPending] = useState<CommunityStatus | null>(null);

  const update = useUpdateCommunityStorage({
    onSuccess: (row) => {
      toast.success(t("communities.statusSaved", { name: row.name }));
    },
    onError: (err) => {
      toast.error(getErrorMessage(err, "settings:communities.statusSaveError"));
    },
    // Close the confirm dialog only once the mutation settles, so its in-flight
    // state is actually observable (the dialog shows "please wait" while saving).
    onSettled: () => setPending(null),
  });

  const apply = (status: CommunityStatus) => {
    update.mutate({ communityId: community.id, data: { status } });
  };

  const handleChange = (value: string) => {
    const next = value as CommunityStatus;
    if (next === community.status) return;
    if (next === CommunityStatus.suspended || next === CommunityStatus.on_hold) {
      setPending(next);
      return;
    }
    apply(next);
  };

  if (
    community.status === CommunityStatus.deleted ||
    !community.allowed_actions.includes(CommunityAction.set_status)
  ) {
    return <CommunityStatusBadge status={community.status} />;
  }

  return (
    <>
      <Select value={community.status} onValueChange={handleChange} disabled={update.isPending}>
        <SelectTrigger
          className="w-36"
          aria-label={t("communities.statusInputLabel", { name: community.name })}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {community.status_choices.map((status) => (
            <SelectItem key={status} value={status}>
              {t(`communities.status.${status}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        title={
          pending === CommunityStatus.on_hold
            ? t("communities.holdConfirm.title", { name: community.name })
            : t("communities.suspendConfirm.title", { name: community.name })
        }
        description={
          pending === CommunityStatus.on_hold
            ? t("communities.holdConfirm.description")
            : t("communities.suspendConfirm.description")
        }
        confirmLabel={
          pending === CommunityStatus.on_hold
            ? t("communities.holdConfirm.confirm")
            : t("communities.suspendConfirm.confirm")
        }
        destructive
        isLoading={update.isPending}
        onConfirm={() => pending && apply(pending)}
      />
    </>
  );
};

/** A community's status as a tag, for whoever cannot change it here. */
const CommunityStatusBadge = ({ status }: { status: CommunityStatus }) => {
  const { t } = useTranslation("settings");
  const variant =
    status === CommunityStatus.deleted || status === CommunityStatus.suspended
      ? "destructive"
      : status === CommunityStatus.active
        ? "secondary"
        : "outline";
  return <Badge variant={variant}>{t(`communities.status.${status}`)}</Badge>;
};

/**
 * Suspending a community, or lifting its suspension, for a reader the row says
 * may (`suspend` / `lift`): a moderator under a live moderate grant on it.
 * Both are confirmed, and each says where the community ends up — a deleted
 * one stops counting down to its destruction while it is suspended, and starts
 * again from the beginning when the suspension is lifted.
 */
const CommunitySuspensionButton = ({ community }: { community: PlatformCommunityStorageRead }) => {
  const { t } = useTranslation(["settings", "common"]);
  const [confirming, setConfirming] = useState(false);
  const lifting = community.allowed_actions.includes(CommunityAction.lift);
  const suspending = community.allowed_actions.includes(CommunityAction.suspend);

  const update = useSetCommunitySuspension({
    onSuccess: (row) => {
      toast.success(
        lifting
          ? t("communities.suspension.lifted", { name: row.name })
          : t("communities.suspension.suspended", { name: row.name })
      );
    },
    onError: (err) => {
      toast.error(getErrorMessage(err, "settings:communities.statusSaveError"));
    },
    onSettled: () => setConfirming(false),
  });

  if (!lifting && !suspending) return null;

  const description = lifting
    ? community.lifts_to === CommunityStatus.deleted
      ? t("communities.suspension.liftToDeleted")
      : t("communities.suspension.liftDescription", {
          status: t(`communities.status.${community.lifts_to ?? CommunityStatus.active}`),
        })
    : community.status === CommunityStatus.deleted
      ? t("communities.suspension.suspendDeleted")
      : t("communities.suspendConfirm.description");

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setConfirming(true)}
        disabled={update.isPending}
        aria-label={
          lifting
            ? t("communities.suspension.liftLabel", { name: community.name })
            : t("communities.suspension.suspendLabel", { name: community.name })
        }
      >
        {lifting ? t("communities.suspension.lift") : t("communities.suspension.suspend")}
      </Button>
      <ConfirmDialog
        open={confirming}
        onOpenChange={(open) => !open && setConfirming(false)}
        title={
          lifting
            ? t("communities.suspension.liftTitle", { name: community.name })
            : t("communities.suspendConfirm.title", { name: community.name })
        }
        description={description}
        confirmLabel={
          lifting ? t("communities.suspension.lift") : t("communities.suspendConfirm.confirm")
        }
        loadingLabel={t("common:submitting")}
        destructive={!lifting}
        isLoading={update.isPending}
        onConfirm={() =>
          update.mutate({ communityId: community.id, data: { suspended: !lifting } })
        }
      />
    </>
  );
};

/**
 * The ways into a community a reader may ask for, from its row: a request
 * for access, or breaking glass. Each opens that form on the Access tab with
 * the community already chosen.
 */
const CommunityAccessMenu = ({ community }: { community: PlatformCommunityStorageRead }) => {
  const { t } = useTranslation("settings");
  const canRequest = community.allowed_actions.includes(CommunityAction.request_access);
  const canBreakGlass = community.allowed_actions.includes(CommunityAction.break_glass);
  // A moderator reaching a community from here is moderating it: suspending
  // it, or looking at what it holds, takes Moderate.
  const { user } = useAuth();
  const level = hasCapability(user, Capability.contentModerate) ? "moderate" : undefined;
  return (
    <RowActionsMenu subject={community.name}>
      {canRequest && (
        <DropdownMenuItem asChild>
          <Link
            to="/settings/operator/access"
            search={{ community: community.id, name: community.name, form: "request", level }}
          >
            <KeyRound className="h-4 w-4" />
            {t("communities.access.request")}
          </Link>
        </DropdownMenuItem>
      )}
      {canBreakGlass && (
        <DropdownMenuItem asChild>
          <Link
            to="/settings/operator/access"
            search={{ community: community.id, name: community.name, form: "break_glass" }}
          >
            <ShieldAlert className="h-4 w-4" />
            {t("communities.access.breakGlass")}
          </Link>
        </DropdownMenuItem>
      )}
    </RowActionsMenu>
  );
};

/**
 * Per-community sign-in entitlement toggle. Flipping it on lets the community configure
 * its own login providers and onboard new accounts through them; withdrawing it
 * closes that config surface and stops new-account onboarding, but never deletes
 * providers or signs existing members out.
 */
export const OperatorDashboardCommunitiesPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  // Reading the list is support work; what each reader may do to a row comes
  // with the row, in `allowed_actions`.
  const canReadCommunities = hasCapability(user, Capability.communitiesRead);

  // Searched, sorted and paged on the server, so the table holds one page of
  // the deployment's communities rather than all of them.
  const table = useServerTableState(Object.values(ListPlatformCommunityStorageSortBy));
  const communitiesQuery = usePlatformCommunities(table.params, {
    enabled: canReadCommunities,
  });
  const rows = communitiesQuery.data?.items ?? [];
  const totalCount = communitiesQuery.data?.total_count ?? 0;
  const { billing } = useAppConfig();
  // Which community's operator settings are open. The sheet reads the row from
  // the query, so a save re-renders it with the saved values.
  const [managingId, setManagingId] = useState<number | null>(null);
  const managing = rows.find((community) => community.id === managingId) ?? null;

  const columns: AppColumnDef<PlatformCommunityStorageRead>[] = [
    {
      accessorKey: "id",
      header: t("communities.columns.id"),
      cell: ({ row }) => (
        <span className="font-mono text-muted-foreground text-sm">{row.original.id}</span>
      ),
    },
    {
      accessorKey: "name",
      header: t("communities.columns.community"),
      cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
    },
    {
      accessorKey: "member_count",
      header: t("communities.columns.users"),
      enableSorting: false,
      cell: ({ row }) => (
        <span className="text-sm tabular-nums">
          {row.original.max_users == null
            ? row.original.member_count
            : `${row.original.member_count} / ${row.original.max_users}`}
        </span>
      ),
    },
    {
      id: "storage",
      header: t("communities.columns.storageLimit"),
      enableSorting: false,
      cell: ({ row }) => (
        <span className="text-muted-foreground text-sm tabular-nums">
          {row.original.max_storage_bytes == null
            ? t("communities.unlimited")
            : `${Number((row.original.max_storage_bytes / 1024 ** 3).toFixed(2))} GB`}
        </span>
      ),
    },
    {
      id: "manage",
      header: "",
      enableSorting: false,
      cell: ({ row }) =>
        row.original.allowed_actions.includes(CommunityAction.manage) ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setManagingId(row.original.id)}
            aria-label={t("communities.sheet.openLabel", { name: row.original.name })}
          >
            {t("communities.sheet.open")}
          </Button>
        ) : null,
    },
    {
      id: "status",
      header: t("communities.columns.status"),
      enableSorting: false,
      cell: ({ row }) => (
        <div className="flex flex-wrap items-center gap-2">
          <CommunityStatusCell community={row.original} />
          <CommunitySuspensionButton community={row.original} />
        </div>
      ),
    },
    // Only when this deployment links a billing portal AND the operator route
    // into it is wired — otherwise the button could only ever fail.
    ...(billing?.operator_handoff
      ? [
          {
            id: "billing",
            header: t("communities.columns.billing"),
            enableSorting: false,
            cell: ({ row }) => <CommunityBillingCell community={row.original} />,
          } satisfies AppColumnDef<PlatformCommunityStorageRead>,
        ]
      : []),
    {
      id: "access",
      header: "",
      enableSorting: false,
      cell: ({ row }) => <CommunityAccessMenu community={row.original} />,
    },
  ];

  if (!canReadCommunities) {
    return <p className="text-muted-foreground text-sm">{t("communities.platformOnly")}</p>;
  }

  if (communitiesQuery.isLoading) {
    return (
      <SkeletonRegion label={t("communities.loading")}>
        <TableSkeleton rows={6} columns={5} />
      </SkeletonRegion>
    );
  }

  if (communitiesQuery.isError || !communitiesQuery.data) {
    return <p className="text-destructive text-sm">{t("communities.loadError")}</p>;
  }

  return (
    <SettingsSection title={t("communities.title")} description={t("communities.description")}>
      <DataTable
        columns={columns}
        data={rows}
        getRowId={(community) => String(community.id)}
        enableFilterInput
        filterInputPlaceholder={t("communities.filterByName")}
        enableResetSorting
        enablePagination
        {...table.tableProps(totalCount)}
      />
      <p className="text-muted-foreground text-xs">
        {billing?.manages_plans ? t("communities.helpTextBilling") : t("communities.helpText")}
      </p>
      <CommunityOperatorSettingsSheet
        community={managing}
        open={managing !== null}
        onOpenChange={(next) => {
          if (!next) setManagingId(null);
        }}
        supportBound={communitiesQuery.data?.support_bound ?? false}
      />
    </SettingsSection>
  );
};
