/**
 * `/settings/properties` — the custom fields this initiative's files,
 * tasks, and events can carry, then each collection's own fields.
 */

import { useTranslation } from "react-i18next";

import { InitiativeSettingsPermissionRequired } from "@/components/initiatives/settings/InitiativeSettingsGuard";
import { InitiativeSettingsPropertiesTab } from "@/components/initiatives/settings/InitiativeSettingsPropertiesTab";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useCollections } from "@/hooks/useCollections";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";

export const InitiativeSettingsPropertiesPage = () => {
  const { t } = useTranslation("files");
  const { initiativeId, canManageMembers } = useInitiativeSettings();
  // Fields are made in a collection's layouts; a collection with some is
  // listed here, where they are renamed, ordered and removed.
  const collections = useCollections(canManageMembers ? initiativeId : null).data?.items ?? [];

  if (!canManageMembers) {
    return <InitiativeSettingsPermissionRequired />;
  }

  return (
    <div className="space-y-6">
      <InitiativeSettingsPropertiesTab initiativeId={initiativeId} />
      {collections
        .filter((collection) => collection.fields.length > 0)
        .map((collection) => (
          <Card key={collection.id}>
            <CardHeader>
              <CardTitle>{t("collections.fields.of", { name: collection.name })}</CardTitle>
            </CardHeader>
            <CardContent>
              <InitiativeSettingsPropertiesTab
                initiativeId={initiativeId}
                collectionId={collection.id}
              />
            </CardContent>
          </Card>
        ))}
    </div>
  );
};
