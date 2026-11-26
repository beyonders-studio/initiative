import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  PluginPlatformConnectionRead,
  PluginServiceRegistrationRead,
} from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useConnectFlow } from "@/hooks/useConnectFlow";
import {
  useConnectForEveryCommunity,
  useDisconnectForEveryCommunity,
} from "@/hooks/usePluginServices";
import { connectingApp } from "@/lib/appConnect";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { localized } from "@/ui/lib/localized";

interface PlatformConnectionsSectionProps {
  registration: PluginServiceRegistrationRead;
  plain?: boolean;
}

/**
 * The plug-in's community connections the operator can connect once for every
 * community. Connected, each community uses it and cannot change it;
 * disconnected, each community connects its own.
 */
export const PlatformConnectionsSection = ({
  registration,
  plain,
}: PlatformConnectionsSectionProps) => {
  const { t, i18n } = useTranslation("settings");
  const flow = useConnectFlow();
  const connect = useConnectForEveryCommunity({
    // The browser goes to the vendor and comes back here; the app has no
    // session in a browser, so it sees the flow to its end (useConnectFlow).
    onSuccess: ({ connect_url }) =>
      connectingApp() ? void flow.open(connect_url) : window.location.assign(connect_url),
  });
  const disconnect = useDisconnectForEveryCommunity({
    onSuccess: () => setEnding(null),
  });
  const [ending, setEnding] = useState<PluginPlatformConnectionRead | null>(null);

  const name = (connection: PluginPlatformConnectionRead) =>
    localized(connection.label, i18n.language) ?? connection.connection_id;

  return (
    <SettingsSection
      plain={plain}
      title={t("pluginServices.platformConnections.title")}
      description={t("pluginServices.platformConnections.help")}
    >
      <ul className="divide-y rounded-md border">
        {registration.platform_connections.map((connection) => (
          <li
            key={connection.connection_id}
            className="flex flex-wrap items-center justify-between gap-3 p-3"
          >
            <div className="min-w-0 space-y-1">
              <p className="font-medium text-sm">{name(connection)}</p>
              <p className="text-muted-foreground text-xs">
                {connection.connected
                  ? t("pluginServices.platformConnections.connectedTo", {
                      account: connection.account_label ?? connection.connection_id,
                    })
                  : t("pluginServices.platformConnections.notConnected")}
              </p>
              {connection.removed && (
                <Badge variant="warning">{t("pluginServices.platformConnections.removed")}</Badge>
              )}
            </div>
            {connection.connected ? (
              <Button type="button" variant="outline" onClick={() => setEnding(connection)}>
                {t("pluginServices.platformConnections.disconnect")}
              </Button>
            ) : (
              <Button
                type="button"
                disabled={!registration.vendor_ready || connect.isPending}
                onClick={() =>
                  connect.mutate({
                    registrationId: registration.id,
                    connectionId: connection.connection_id,
                  })
                }
              >
                {connect.isPending
                  ? t("pluginServices.platformConnections.connecting")
                  : t("pluginServices.platformConnections.connect")}
              </Button>
            )}
          </li>
        ))}
      </ul>
      {!registration.vendor_ready && (
        <p className="text-muted-foreground text-xs">
          {t("pluginServices.platformConnections.needsVendor")}
        </p>
      )}
      <ConfirmDialog
        open={ending !== null}
        onOpenChange={(open) => !open && setEnding(null)}
        title={t("pluginServices.platformConnections.disconnectTitle", {
          name: ending ? name(ending) : "",
        })}
        description={t("pluginServices.platformConnections.disconnectHelp")}
        confirmLabel={t("pluginServices.platformConnections.disconnect")}
        destructive
        isLoading={disconnect.isPending}
        onConfirm={() =>
          ending &&
          disconnect.mutate({
            registrationId: registration.id,
            connectionId: ending.connection_id,
          })
        }
      />
    </SettingsSection>
  );
};
