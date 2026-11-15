/**
 * A community's plug-ins as staff see them: each one's state there, and what
 * the reader may do to it.
 *
 * The server works out each plug-in's `allowed_actions` for the reader, so a
 * control they would be refused is never drawn: a moderator suspends and
 * lifts, and an operator also sets the status, except where billing sets the
 * community's plan, where the status is billing's and is shown as text.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  CommunityPluginAction,
  type CommunityPluginStateRead,
  PluginInstallStatus,
  PluginState,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getListCommunityPluginStatesQueryKey,
  useListCommunityPluginStates,
  useSetCommunityPluginStatus,
  useSetCommunityPluginSuspension,
} from "@/api/generated/settings/settings";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { queryClient } from "@/lib/queryClient";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { formatDate } from "@/ui/lib/formatDate";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { StatusMessage } from "@/ui/status-message";

export const CommunityPluginsList = ({ communityId }: { communityId: number }) => {
  const { t } = useTranslation(["settings", "common"]);
  const [suspending, setSuspending] = useState<CommunityPluginStateRead | null>(null);
  const plugins = useListCommunityPluginStates(communityId);

  const settled = {
    onError: (error: unknown) =>
      toast.error(getErrorMessage(error, "settings:communities.plugins.saveError")),
    onSettled: () => {
      setSuspending(null);
      void queryClient.invalidateQueries({
        queryKey: getListCommunityPluginStatesQueryKey(communityId),
      });
    },
  };
  const suspension = useSetCommunityPluginSuspension({
    mutation: {
      ...settled,
      onSuccess: (row, { data }) =>
        toast.success(
          t(data.suspended ? "communities.plugins.suspended" : "communities.plugins.lifted", {
            name: row.name ?? row.listing_uid,
          })
        ),
    },
  });
  const status = useSetCommunityPluginStatus({
    mutation: {
      ...settled,
      onSuccess: (row) =>
        toast.success(t("communities.plugins.statusSaved", { name: row.name ?? row.listing_uid })),
    },
  });
  const pending = suspension.isPending || status.isPending;

  if (plugins.isLoading) {
    return (
      <SkeletonRegion>
        <ListSkeleton rows={2} avatar={false} rowClassName="rounded-md border px-4 py-3" />
      </SkeletonRegion>
    );
  }
  if (plugins.isError || !plugins.data) return <StatusMessage onRetry={plugins.refetch} />;
  if (plugins.data.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("communities.plugins.empty")}</p>;
  }

  const suspend = (plugin: CommunityPluginStateRead, suspended: boolean) =>
    suspension.mutate({ communityId, installId: plugin.install_id, data: { suspended } });

  return (
    <>
      <ul className="space-y-3">
        {plugins.data.map((plugin) => {
          const name = plugin.name ?? plugin.listing_uid;
          const actions = plugin.allowed_actions;
          return (
            <li
              key={plugin.install_id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-md border px-4 py-3"
            >
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-medium text-sm">{name}</p>
                  {plugin.state === PluginState.suspended && (
                    <Badge variant="destructive">{t("communities.plugins.status.suspended")}</Badge>
                  )}
                </div>
                {plugin.suspended_at && (
                  <p className="text-muted-foreground text-xs">
                    {t("communities.plugins.suspendedOn", {
                      date: formatDate(plugin.suspended_at),
                    })}
                  </p>
                )}
                {plugin.status === PluginInstallStatus.deleted && plugin.uninstall_at && (
                  <p className="text-muted-foreground text-xs">
                    {t("communities.plugins.removedOn", { date: formatDate(plugin.uninstall_at) })}
                  </p>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                {actions.includes(CommunityPluginAction.set_status) ? (
                  <Select
                    value={plugin.status}
                    disabled={pending}
                    onValueChange={(value) =>
                      value !== plugin.status &&
                      status.mutate({
                        communityId,
                        installId: plugin.install_id,
                        data: { status: value as PluginInstallStatus },
                      })
                    }
                  >
                    <SelectTrigger
                      className="w-36"
                      aria-label={t("communities.plugins.statusLabel", { name })}
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {Object.values(PluginInstallStatus).map((choice) => (
                        <SelectItem key={choice} value={choice}>
                          {t(`communities.plugins.status.${choice}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <span className="text-sm">
                    {t(`communities.plugins.status.${plugin.status}`)}
                  </span>
                )}
                {actions.includes(CommunityPluginAction.lift) && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={pending}
                    onClick={() => suspend(plugin, false)}
                    aria-label={t("communities.plugins.liftLabel", { name })}
                  >
                    {t("communities.plugins.lift")}
                  </Button>
                )}
                {actions.includes(CommunityPluginAction.suspend) && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="text-destructive"
                    disabled={pending}
                    onClick={() => setSuspending(plugin)}
                    aria-label={t("communities.plugins.suspendLabel", { name })}
                  >
                    {t("communities.plugins.suspend")}
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      <ConfirmDialog
        open={suspending !== null}
        onOpenChange={(open) => !open && setSuspending(null)}
        title={t("communities.plugins.suspendTitle", {
          name: suspending?.name ?? suspending?.listing_uid ?? "",
        })}
        description={t("communities.plugins.suspendDescription")}
        confirmLabel={t("communities.plugins.suspend")}
        loadingLabel={t("common:submitting")}
        destructive
        isLoading={suspension.isPending}
        onConfirm={(event) => {
          // Kept open until the change settles, so its progress shows.
          event.preventDefault();
          if (suspending) suspend(suspending, true);
        }}
      />
    </>
  );
};
