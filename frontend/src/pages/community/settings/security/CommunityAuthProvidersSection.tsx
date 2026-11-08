/**
 * Which of the deployment's sign-in providers this community counts as its own.
 *
 * A community does not configure a provider and does not sign anybody in —
 * whoever runs the deployment does both — so there is no issuer here, no
 * client id and no secret. What a community says is which arrivals are its
 * own, and whether they join on sight: "our Google Workspace" rather than
 * "Google".
 *
 * That first part is the narrowing. Google will vouch for anybody with a
 * Google account, so a community connecting to it says which workspace domain
 * is theirs. A community whose provider is its own identity provider needs
 * none: it already only holds their people.
 *
 * A connection of the community's own also says whether the deployment's
 * placement rules for that provider may place people here, beside the
 * community's own rules. Connecting, taking over the deployment's arrangement
 * and editing are all the one wizard.
 */

import { Pencil, Plus, Power, Unplug } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CommunityProviderConnectionRead,
  CommunityProviderConnectionUpdate,
  ConnectableProviderRead,
} from "@/api/generated/initiativeAPI.schemas";
import { ProviderMark } from "@/components/auth/ProviderMark";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import {
  useCommunityProviderConnections,
  useConnectableProviders,
  useDisconnectProvider,
  useUpdateProviderConnection,
} from "@/hooks/useCommunityAuthPolicy";
import { useServer } from "@/hooks/useServer";
import { toast } from "@/lib/mascotToast";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { CopyButton } from "@/ui/copy-button";
import {
  DropdownMenuCheckboxItem,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/ui/dropdown-menu";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/ui/empty";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { RowActionsMenu } from "@/ui/row-actions-menu";

import { ConnectSignInWizard, NARROWING_CLAIMS } from "./ConnectSignInWizard";

export const CommunityAuthProvidersSection = ({
  communityId,
  communityName,
}: {
  communityId: number;
  communityName: string;
}) => {
  const { t } = useTranslation(["settings", "common"]);
  const connectionsQuery = useCommunityProviderConnections(communityId);
  const availableQuery = useConnectableProviders(communityId);
  const updateConnection = useUpdateProviderConnection(communityId);
  const disconnect = useDisconnectProvider(communityId);
  const { getServerOrigin } = useServer();

  const [removing, setRemoving] = useState<CommunityProviderConnectionRead | null>(null);
  // The wizard opens on the picker, or on a connection to take over or edit.
  const [wizard, setWizard] = useState<{
    open: boolean;
    connection: CommunityProviderConnectionRead | null;
  }>({ open: false, connection: null });
  const openWizard = (connection: CommunityProviderConnectionRead | null = null) =>
    setWizard({ open: true, connection });

  const connections = connectionsQuery.data ?? [];
  // Only what this community said itself: a provider it merely inherits is
  // still one it can connect to, which is how it takes the arrangement over.
  const connectedIds = new Set(
    connections.filter((row) => !row.inherited).map((row) => row.provider_id)
  );
  // A provider already in use is still listed by the server (that is what
  // keeps one registered for this community visible to it), so the picker
  // leaves out the ones there is nothing left to do with.
  const choosable = (availableQuery.data ?? []).filter(
    (row: ConnectableProviderRead) => !connectedIds.has(row.id)
  );

  const change = (row: CommunityProviderConnectionRead, data: CommunityProviderConnectionUpdate) =>
    updateConnection.mutate({ connectionId: row.id as number, data });

  // The community's shareable sign-in URL, built on the server's origin (which
  // is the app's own origin on web, or the configured server on native).
  const memberLoginUrl = `${getServerOrigin() ?? window.location.origin}/community/${communityId}/login`;
  const empty = !connectionsQuery.isLoading && connections.length === 0;

  return (
    <SettingsSection
      title={t("communityAuth.connections.title")}
      description={t("communityAuth.connections.description")}
      action={
        empty ? null : (
          <Button type="button" onClick={() => openWizard()} disabled={choosable.length === 0}>
            <Plus className="h-4 w-4" />
            {t("communityAuth.connections.connect")}
          </Button>
        )
      }
    >
      {connectionsQuery.isLoading ? (
        <SkeletonRegion>
          <ListSkeleton rows={3} />
        </SkeletonRegion>
      ) : empty ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyTitle>{t("communityAuth.emptyState.title")}</EmptyTitle>
            <EmptyDescription>
              {choosable.length === 0
                ? t("communityAuth.connections.noneOffered")
                : t("communityAuth.emptyState.body")}
            </EmptyDescription>
          </EmptyHeader>
          {choosable.length > 0 && (
            <EmptyContent>
              <Button type="button" onClick={() => openWizard()}>
                {t("communityAuth.emptyState.button")}
              </Button>
            </EmptyContent>
          )}
        </Empty>
      ) : (
        <>
          <ul className="divide-y rounded-md border">
            {connections.map((row) => (
              <li key={row.provider_id} className="flex items-center gap-3 px-3 py-3">
                <ProviderMark icon={row.provider_icon} />
                <div className="min-w-0 flex-1 space-y-0.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{row.provider_display_name}</span>
                    {!row.login_ready ? (
                      <Badge variant="outline">{t("communityAuth.connections.notReady")}</Badge>
                    ) : row.inherited ? (
                      <Badge variant="secondary">{t("communityAuth.connections.inherited")}</Badge>
                    ) : row.enabled ? (
                      <Badge variant="outline" className="gap-1.5">
                        <span aria-hidden="true" className="size-1.5 rounded-full bg-success" />
                        {t("settingsSection.on")}
                      </Badge>
                    ) : (
                      <Badge variant="outline">{t("settingsSection.off")}</Badge>
                    )}
                  </div>
                  <p className="text-muted-foreground text-sm">
                    {[
                      row.claim && row.claim_values.length > 0
                        ? t("communityAuth.connections.narrowedTo", {
                            claim: (NARROWING_CLAIMS as readonly string[]).includes(row.claim)
                              ? t(
                                  `communityAuth.connections.claimOptions.${row.claim as (typeof NARROWING_CLAIMS)[number]}`
                                )
                              : row.claim,
                            values: row.claim_values.join(", "),
                          })
                        : t("communityAuth.connections.anyoneItVouchesFor"),
                      row.auto_join && row.narrowing_approved
                        ? t("communityAuth.connections.joinsOnArrival")
                        : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                  {row.auto_join && !row.narrowing_approved && (
                    <p className="text-muted-foreground text-xs">
                      {t("communityAuth.connections.joinsOnceAgreed")}
                    </p>
                  )}
                </div>
                {row.inherited || row.id === null ? (
                  // The deployment's arrangement has nothing of the community's
                  // own to change; it is taken over instead.
                  <Button type="button" variant="outline" size="sm" onClick={() => openWizard(row)}>
                    {t("communityAuth.connections.makeItOurs")}
                  </Button>
                ) : (
                  <RowActionsMenu subject={row.provider_display_name}>
                    <DropdownMenuItem onSelect={() => openWizard(row)}>
                      <Pencil className="h-4 w-4" />
                      {t("common:edit")}
                    </DropdownMenuItem>
                    <DropdownMenuCheckboxItem
                      checked={row.accepts_provider_placement}
                      onCheckedChange={(checked) =>
                        change(row, { accepts_provider_placement: checked === true })
                      }
                    >
                      {t("communityAuth.connections.acceptsPlacementLabel")}
                    </DropdownMenuCheckboxItem>
                    <DropdownMenuItem onSelect={() => change(row, { enabled: !row.enabled })}>
                      <Power className="h-4 w-4" />
                      {row.enabled
                        ? t("communityAuth.connections.turnOff")
                        : t("communityAuth.connections.turnOn")}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      className="text-destructive"
                      onSelect={() => setRemoving(row)}
                    >
                      <Unplug className="h-4 w-4" />
                      {t("communityAuth.connections.disconnect")}
                    </DropdownMenuItem>
                  </RowActionsMenu>
                )}
              </li>
            ))}
          </ul>
          <SettingsRow
            label={t("communityAuth.shareUrl.title")}
            description={t("communityAuth.shareUrl.description", { community: communityName })}
            below={
              <div className="flex items-center gap-2">
                <code className="min-w-0 flex-1 truncate rounded bg-muted px-2 py-1.5 text-sm">
                  {memberLoginUrl}
                </code>
                <CopyButton
                  value={memberLoginUrl}
                  label={t("communityAuth.shareUrl.copy")}
                  copiedMessage={t("communityAuth.shareUrl.copied")}
                />
              </div>
            }
          />
        </>
      )}

      {/* Shown only where the community may configure providers, which is
          also what setting the requirement asks for. */}
      <ConnectSignInWizard
        communityId={communityId}
        open={wizard.open}
        onOpenChange={(open) => setWizard((previous) => ({ ...previous, open }))}
        canRequire
        connection={wizard.connection}
      />

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        title={t("communityAuth.connections.disconnectTitle", {
          name: removing?.provider_display_name ?? "",
        })}
        description={t("communityAuth.connections.disconnectDescription")}
        confirmLabel={t("communityAuth.connections.disconnect")}
        destructive
        isLoading={disconnect.isPending}
        onConfirm={() => {
          // Only a connection of this community's own reaches here; an
          // inherited row offers to be taken over rather than removed.
          if (removing?.id == null) return;
          disconnect.mutate(removing.id, {
            onSuccess: () => {
              toast.success(t("communityAuth.connections.disconnected"));
              setRemoving(null);
            },
          });
        }}
      />
    </SettingsSection>
  );
};
