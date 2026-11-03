/**
 * `/settings/access` — who else can reach this tool entity.
 *
 * Write access to the entity is what the tab bar offers this section on, and
 * the section refuses it on its own too: the address is typeable, and sharing
 * is the last privilege gate in front of the entity's contents.
 *
 * Above who it is shared with, for someone who may share it: who has asked.
 */

import { useTranslation } from "react-i18next";

import { ShareControl } from "@/components/access/ShareControl";
import { ShareRequestsCard } from "@/components/access/ShareRequests";
import { useToolSettings } from "@/components/tools/settings/ToolSettingsContext";
import { ToolSettingsPermissionRequired } from "@/components/tools/settings/ToolSettingsGuard";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { toast } from "@/lib/mascotToast";

export const ToolSettingsAccessPage = () => {
  const { t } = useTranslation(["common", "access"]);
  const { tool, entity, setGrants } = useToolSettings();

  if (!entity.can.edit) {
    return <ToolSettingsPermissionRequired />;
  }

  const ownerId = entity.grants.find((grant) => grant.level === "owner")?.user_id ?? null;

  return (
    <div className="space-y-6">
      {entity.can.share ? <ShareRequestsCard tool={tool} entityId={entity.id} /> : null}
      <Card>
        <CardHeader>
          <CardDescription>{t("access:share.settingsDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <ShareControl
            initiativeId={entity.initiative_id ?? 0}
            grants={entity.grants}
            ownerId={ownerId}
            ownerPlugin={entity.owner_plugin ?? null}
            onChange={(grants) =>
              setGrants.mutate(grants, {
                onSuccess: () => toast.success(t("common:toolSettings.permissionsUpdated")),
              })
            }
            disabled={!entity.can.share || setGrants.isPending}
          />
        </CardContent>
      </Card>
    </div>
  );
};
