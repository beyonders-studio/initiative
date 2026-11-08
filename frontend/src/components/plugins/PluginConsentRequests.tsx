/**
 * What a plug-in has asked to do as you, one line per purpose, and your answer.
 *
 * A plug-in asks for one purpose at a time — "comment on the linked issue as the
 * person who closed it" — in its own words, which is why the label is shown
 * quoted and attributed to the plug-in rather than as Initiative's. Each line is
 * answered on its own: allow reading, allow reading and changes (only when the
 * plug-in asked for that much), decline, and later withdraw. The plug-in-wide request,
 * if the plug-in made one, comes first.
 *
 * Every answer is the viewer's own. Nothing here names or answers for anybody
 * else.
 */

import { useTranslation } from "react-i18next";

import {
  type CommunityPluginConsentRead,
  ConsentAccess,
  ConsentStatus,
} from "@/api/generated/initiativeAPI.schemas";
import { useGrantPluginConsent, useRevokePluginConsent } from "@/hooks/useCommunityPluginDetail";
import { useInitiatives } from "@/hooks/useInitiatives";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";

export interface PluginConsentRequestsProps {
  pluginId: number;
  pluginName: string;
  consents: CommunityPluginConsentRead[];
}

export function PluginConsentRequests({
  pluginId,
  pluginName,
  consents,
}: PluginConsentRequestsProps) {
  const { t } = useTranslation(["plugins", "common"]);
  const grant = useGrantPluginConsent(pluginId);
  const revoke = useRevokePluginConsent(pluginId);
  const initiatives = useInitiatives({ enabled: consents.some((c) => c.initiative_id) });
  const busy = grant.isPending || revoke.isPending;

  const initiativeName = (id: number) =>
    initiatives.data?.find((initiative) => initiative.id === id)?.name ?? null;

  const allow = async (consent: CommunityPluginConsentRead, access: ConsentAccess) => {
    try {
      await grant.mutateAsync({ consentId: consent.id, access });
      toast.success(t("plugins:consent.allowed", { name: pluginName }));
    } catch (error) {
      toast.error(getErrorMessage(error, "plugins:consent.failed"));
    }
  };

  const end = async (consent: CommunityPluginConsentRead) => {
    const declining = consent.status === ConsentStatus.pending;
    try {
      await revoke.mutateAsync(consent.id);
      toast.success(
        declining
          ? t("plugins:consent.declinedToast", { name: pluginName })
          : t("plugins:consent.withdrawnToast", { name: pluginName })
      );
    } catch (error) {
      toast.error(getErrorMessage(error, "plugins:consent.failed"));
    }
  };

  return (
    <div className="space-y-2">
      <h4 className="font-medium text-sm">{t("plugins:consent.title")}</h4>
      <p className="text-muted-foreground text-xs">
        {t("plugins:consent.description", { name: pluginName })}
      </p>
      <ul className="space-y-2">
        {consents.map((consent) => {
          const askedForChanges = consent.requested_access === ConsentAccess.read_write;
          const granted = consent.status === ConsentStatus.granted;
          const where =
            consent.initiative_id != null ? initiativeName(consent.initiative_id) : null;
          return (
            <li key={consent.id} className="space-y-2 rounded-md border p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0 space-y-0.5">
                  <p className="break-words text-sm">
                    {t("plugins:consent.inTheirWords", { name: pluginName, label: consent.label })}
                  </p>
                  <p className="text-muted-foreground text-xs">
                    {[
                      consent.purpose == null ? t("plugins:consent.pluginWide") : null,
                      consent.initiative_id == null
                        ? t("plugins:consent.anywhere")
                        : where
                          ? t("plugins:consent.inInitiative", { initiative: where })
                          : t("plugins:consent.inOneInitiative"),
                      askedForChanges
                        ? t("plugins:consent.askedReadWrite")
                        : t("plugins:consent.askedRead"),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </div>
                <Badge variant={granted ? "secondary" : "outline"}>{t(statusKey(consent))}</Badge>
              </div>
              <div className="flex flex-wrap gap-2">
                {!(granted && consent.granted_access === ConsentAccess.read) && (
                  <Button
                    size="sm"
                    variant={granted ? "outline" : "default"}
                    disabled={busy}
                    onClick={() => allow(consent, ConsentAccess.read)}
                  >
                    {granted ? t("plugins:consent.readOnly") : t("plugins:consent.allowRead")}
                  </Button>
                )}
                {askedForChanges &&
                  !(granted && consent.granted_access === ConsentAccess.read_write) && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy}
                      onClick={() => allow(consent, ConsentAccess.read_write)}
                    >
                      {t("plugins:consent.allowReadWrite")}
                    </Button>
                  )}
                {(granted || consent.status === ConsentStatus.pending) && (
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => end(consent)}>
                    {granted ? t("plugins:consent.withdraw") : t("plugins:consent.decline")}
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function statusKey(consent: CommunityPluginConsentRead) {
  switch (consent.status) {
    case ConsentStatus.granted:
      return consent.granted_access === ConsentAccess.read_write
        ? "plugins:consent.statusReadWrite"
        : "plugins:consent.statusRead";
    case ConsentStatus.declined:
      return "plugins:consent.statusDeclined";
    case ConsentStatus.revoked:
      return "plugins:consent.statusRevoked";
    default:
      return "plugins:consent.statusPending";
  }
}
