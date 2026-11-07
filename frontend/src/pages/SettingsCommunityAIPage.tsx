import { useTranslation } from "react-i18next";

import {
  AIConnectionManager,
  type ConnectionMutations,
} from "@/components/settings/AIConnectionManager";
import { FormSkeleton, SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAIEnabled } from "@/hooks/useAIEnabled";
import {
  useCommunityConnections,
  useCreateCommunityConnection,
  useDeleteCommunityConnection,
  useFetchCommunityConnectionModels,
  useTestCommunityConnection,
  useUpdateCommunityConnection,
} from "@/hooks/useAISettings";
import { useCommunities } from "@/hooks/useCommunities";
import { getProvidersForScope } from "@/lib/ai-providers";

/**
 * The seat's AI surface: the community's own AI connections when the platform
 * is in `community` mode. Whether AI may be used here at all is a restriction,
 * on Security.
 */
export const SettingsCommunityAIPage = () => {
  const { t } = useTranslation("settings");
  const { activeCommunity, activeCommunityReadOnly } = useCommunities();
  // The seat, not admin-or-above: connecting a provider says what leaves
  // the community. The tab is gated the same way; this is the direct-URL half.
  const holdsTheSeat = Boolean(activeCommunity?.can.seat) && !activeCommunityReadOnly;

  // The resolved settings name the global AI mode, and every member reads them.
  const modeQuery = useAIEnabled();
  const mode = modeQuery.data?.source;
  // Whoever runs the server can take the community's own connections over;
  // the ones the community set up are kept, just not used, and not edited here.
  const connectionsClosed = Boolean(activeCommunity?.closed_surfaces?.includes("ai_connections"));
  const canManageConnections = mode === "community" && !connectionsClosed;

  const connectionsQuery = useCommunityConnections({
    enabled: Boolean(holdsTheSeat) && canManageConnections,
  });

  const mutations: ConnectionMutations = {
    create: useCreateCommunityConnection(),
    update: useUpdateCommunityConnection(),
    remove: useDeleteCommunityConnection(),
    test: useTestCommunityConnection(),
    fetchModels: useFetchCommunityConnectionModels(),
  };

  if (!holdsTheSeat) {
    return <p className="text-muted-foreground text-sm">{t("communityAI.adminOnly")}</p>;
  }

  if (modeQuery.isLoading) {
    return (
      <SkeletonRegion label={t("ai.loading")}>
        <FormSkeleton fields={2} />
      </SkeletonRegion>
    );
  }

  if (modeQuery.isError || !modeQuery.data) {
    return <p className="text-destructive text-sm">{t("ai.loadError")}</p>;
  }

  if (mode === "disabled") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("communityAI.title")}</CardTitle>
          <CardDescription>{t("communityAI.disabledDescription")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="pt-6">
        {canManageConnections ? (
          <AIConnectionManager
            scope="community"
            connections={connectionsQuery.data ?? []}
            isLoading={connectionsQuery.isLoading}
            isError={connectionsQuery.isError}
            providers={getProvidersForScope("community")}
            mutations={mutations}
          />
        ) : (
          <p className="text-muted-foreground text-sm">
            {mode === "platform"
              ? t("communityAI.managedByPlatform")
              : t("communityAI.managedByServer")}
          </p>
        )}
      </CardContent>
    </Card>
  );
};
