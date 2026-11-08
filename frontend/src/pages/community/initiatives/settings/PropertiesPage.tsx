/**
 * `/settings/properties` — the custom fields this initiative's files,
 * tasks, and events can carry.
 */

import { InitiativeSettingsPropertiesTab } from "@/components/initiatives/InitiativeSettingsPropertiesTab";
import { SettingsPermissionRequired } from "@/components/settings/SettingsPermissionRequired";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";

export const PropertiesPage = () => {
  const { initiativeId, canManageMembers } = useInitiativeSettings();

  if (!canManageMembers) {
    return <SettingsPermissionRequired scope="initiative" />;
  }

  return <InitiativeSettingsPropertiesTab initiativeId={initiativeId} />;
};
