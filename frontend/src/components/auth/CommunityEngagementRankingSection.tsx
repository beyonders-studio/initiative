/**
 * Community → Security: whether search orders this community's content by how
 * many members engaged with it lately.
 *
 * The deployment is asked the same question and off wins, so where it has
 * already said no, the switch says so instead of offering a choice.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  useCommunityAuthSettings,
  useUpdateCommunityAuthSettings,
} from "@/hooks/useCommunityAuthPolicy";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";

export const CommunityEngagementRankingSection = ({ communityId }: { communityId: number }) => {
  const { t } = useTranslation("settings");
  const query = useCommunityAuthSettings(communityId);
  const update = useUpdateCommunityAuthSettings(communityId);
  const [error, setError] = useState<string | null>(null);

  const saved = query.data;
  if (!saved) return null;

  const allowed = saved.engagement_ranking_allowed_by_platform;
  // Set for this community by whoever runs the server.
  const fixed = saved.set_by_deployment.includes("allow_engagement_ranking");
  const change = (next: boolean) => {
    setError(null);
    update.mutate(
      { allow_engagement_ranking: next },
      {
        onSuccess: () => toast.success(t("communityEngagementRanking.saved")),
        onError: (err: unknown) =>
          setError(getErrorMessage(err, "settings:communityEngagementRanking.error")),
      }
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("communityEngagementRanking.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1">
            <Label htmlFor="community-engagement-ranking" className="font-medium">
              {t("communityEngagementRanking.label")}
            </Label>
            <p className="text-muted-foreground text-sm">
              {!allowed
                ? t("communityEngagementRanking.platformHelp")
                : fixed
                  ? t("communityAuth.setByDeployment")
                  : t("communityEngagementRanking.help")}
            </p>
          </div>
          <Switch
            id="community-engagement-ranking"
            checked={saved.allow_engagement_ranking && allowed}
            onCheckedChange={change}
            disabled={update.isPending || !allowed || fixed}
          />
        </div>
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
};
