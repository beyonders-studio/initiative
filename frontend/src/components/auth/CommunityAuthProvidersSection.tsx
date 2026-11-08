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
 * community's own rules.
 */

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CommunityProviderConnectionRead,
  ConnectableProviderRead,
} from "@/api/generated/initiativeAPI.schemas";
import { ProviderMark } from "@/components/auth/ProviderMark";
import {
  useCommunityProviderConnections,
  useConnectableProviders,
  useDisconnectProvider,
  useUpdateProviderConnection,
} from "@/hooks/useCommunityAuthPolicy";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { Label } from "@/ui/label";
import { Switch } from "@/ui/switch";

export const CommunityAuthProvidersSection = ({
  communityId,
  onConnect,
}: {
  communityId: number;
  /** Opens the setup wizard. Connecting a provider is a guided flow with
   *  four questions in it, and this card used to carry a second, shorter
   *  version of the first two — two ways to do one thing, and two places to
   *  keep the narrowing honest. There is one now, and this asks for it. */
  onConnect: (providerId?: number) => void;
}) => {
  const { t } = useTranslation("settings");
  const connectionsQuery = useCommunityProviderConnections(communityId);
  const availableQuery = useConnectableProviders(communityId);
  const updateConnection = useUpdateProviderConnection(communityId);
  const disconnect = useDisconnectProvider(communityId);

  const [removing, setRemoving] = useState<CommunityProviderConnectionRead | null>(null);

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

  /** Take over an arrangement the deployment answered for. The wizard opens
   *  on that provider and seeds itself from the inherited row, so the
   *  community starts from what is already in force rather than a blank
   *  form; saving writes a connection of its own, which shadows the default
   *  from then on. */
  const adopt = (row: CommunityProviderConnectionRead) => onConnect(row.provider_id);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle>{t("communityAuth.connections.title")}</CardTitle>
          <CardDescription>{t("communityAuth.connections.description")}</CardDescription>
        </div>
        <Button type="button" onClick={() => onConnect()} disabled={choosable.length === 0}>
          <Plus className="h-4 w-4" />
          {t("communityAuth.connections.connect")}
        </Button>
      </CardHeader>
      <CardContent>
        {connectionsQuery.isLoading ? (
          <p className="text-muted-foreground text-sm">{t("authProviders.loading")}</p>
        ) : connections.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {choosable.length === 0
              ? t("communityAuth.connections.noneOffered")
              : t("communityAuth.connections.empty")}
          </p>
        ) : (
          <ul className="divide-y rounded-md border">
            {connections.map((row) => (
              <li key={row.id} className="flex items-center justify-between gap-4 px-3 py-3">
                <div className="flex min-w-0 items-start gap-3">
                  <ProviderMark icon={row.provider_icon} className="mt-0.5" />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{row.provider_display_name}</span>
                      {row.inherited && (
                        <Badge variant="outline">{t("communityAuth.connections.inherited")}</Badge>
                      )}
                      {!row.enabled && (
                        <Badge variant="outline">{t("authProviders.disabledBadge")}</Badge>
                      )}
                      {!row.login_ready && (
                        <Badge variant="outline">{t("communityAuth.connections.notReady")}</Badge>
                      )}
                    </div>
                    <p className="text-muted-foreground text-sm">
                      {row.claim && row.claim_values.length > 0
                        ? t("communityAuth.connections.narrowedTo", {
                            claim: row.claim,
                            values: row.claim_values.join(", "),
                          })
                        : t("communityAuth.connections.anyoneItVouchesFor")}
                    </p>
                    {row.auto_join && (
                      <p className="text-muted-foreground text-xs">
                        {row.narrowing_approved
                          ? t("communityAuth.connections.joinsOnArrival")
                          : t("communityAuth.connections.joinsOnceAgreed")}
                      </p>
                    )}
                    {/* Only a connection of this community's own carries the
                        answer; an inherited row has none to change. */}
                    {!row.inherited && row.id !== null && (
                      <div className="mt-2 flex items-start gap-2">
                        <Switch
                          id={`accepts-placement-${row.id}`}
                          className="mt-0.5"
                          checked={row.accepts_provider_placement}
                          onCheckedChange={(checked) =>
                            updateConnection.mutate(
                              {
                                connectionId: row.id as number,
                                data: { accepts_provider_placement: Boolean(checked) },
                              },
                              {
                                onError: (error) =>
                                  toast.error(
                                    getErrorMessage(
                                      error,
                                      "settings:communityAuth.connections.connectError"
                                    )
                                  ),
                              }
                            )
                          }
                        />
                        <div className="space-y-0.5">
                          <Label htmlFor={`accepts-placement-${row.id}`} className="text-sm">
                            {t("communityAuth.connections.acceptsPlacementLabel")}
                          </Label>
                          <p className="text-muted-foreground text-xs">
                            {t("communityAuth.connections.acceptsPlacementHelp")}
                          </p>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  {row.inherited || row.id === null ? (
                    <Button type="button" variant="outline" size="sm" onClick={() => adopt(row)}>
                      {t("communityAuth.connections.makeItOurs")}
                    </Button>
                  ) : (
                    <>
                      <Switch
                        aria-label={t("authProviders.enabledLabel")}
                        checked={row.enabled}
                        onCheckedChange={(checked) =>
                          updateConnection.mutate(
                            {
                              connectionId: row.id as number,
                              data: { enabled: Boolean(checked) },
                            },
                            {
                              onError: (error) =>
                                toast.error(
                                  getErrorMessage(
                                    error,
                                    "settings:communityAuth.connections.connectError"
                                  )
                                ),
                            }
                          )
                        }
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="text-destructive"
                        aria-label={t("communityAuth.connections.disconnect")}
                        onClick={() => setRemoving(row)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>

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
            onError: (error) =>
              toast.error(
                getErrorMessage(error, "settings:communityAuth.connections.connectError")
              ),
          });
        }}
      />
    </Card>
  );
};
