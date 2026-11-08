import { useTranslation } from "react-i18next";

import { ActorKind } from "@/api/generated/initiativeAPI.schemas";
import { useCommunityPlugins } from "@/hooks/useCommunityPlugins";

/**
 * What to call whoever did something when it was not a member: the plug-in
 * by its name, or "A plug-in" where the reader cannot list the community's
 * plug-ins or it has been removed; Initiative for the system.
 */
export const useActorName = () => {
  const { t } = useTranslation("common");
  const plugins = useCommunityPlugins();
  return (kind: ActorKind, installId: number | null | undefined): string =>
    kind === ActorKind.system
      ? t("appName")
      : (plugins.data?.items.find((plugin) => plugin.id === installId)?.name ?? t("aPlugin"));
};
