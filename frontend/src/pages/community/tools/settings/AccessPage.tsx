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

import { ShareRequestsCard } from "@/components/access/ShareRequests";
import { SharingSettings } from "@/components/access/SharingSettings";
import { SettingsPermissionRequired } from "@/components/settings/SettingsPermissionRequired";
import { Card, CardContent, CardDescription, CardHeader } from "@/ui/card";

import { useToolSettings } from "./ToolSettingsContext";

export const AccessPage = () => {
  const { t } = useTranslation("access");
  const { tool, entity, setGrants } = useToolSettings();

  if (!entity.can.edit) {
    return <SettingsPermissionRequired scope="tool" />;
  }

  return (
    <div className="space-y-6">
      {entity.can.share ? <ShareRequestsCard tool={tool} entityId={entity.id} /> : null}
      <Card>
        <CardHeader>
          <CardDescription>{t("share.settingsDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <SharingSettings
            initiativeId={entity.initiative_id ?? 0}
            grants={entity.grants}
            ownerPlugin={entity.owner_plugin}
            canShare={entity.can.share}
            setGrants={setGrants}
          />
        </CardContent>
      </Card>
    </div>
  );
};
