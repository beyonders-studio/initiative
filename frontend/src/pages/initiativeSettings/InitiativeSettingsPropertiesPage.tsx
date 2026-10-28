/**
 * `/settings/properties` — the custom fields this initiative's files,
 * tasks, and events can carry.
 */

import { InitiativeSettingsPermissionRequired } from "@/components/initiatives/settings/InitiativeSettingsGuard";
import { InitiativeSettingsPropertiesTab } from "@/components/initiatives/settings/InitiativeSettingsPropertiesTab";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";

export const InitiativeSettingsPropertiesPage = () => {
  const { initiativeId, canManageMembers } = useInitiativeSettings();

  if (!canManageMembers) {
    return <InitiativeSettingsPermissionRequired />;
  }

  return <InitiativeSettingsPropertiesTab initiativeId={initiativeId} />;
};
