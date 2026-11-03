/**
 * Community → AI: whether AI features may send this community's content to a
 * provider at all.
 *
 * The seat's answer narrows what the server offers and never widens it: with
 * it off, no connection is used here, whoever set one up.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { invalidate, q } from "@/api/query-keys";
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

export const CommunityAISwitchSection = ({ communityId }: { communityId: number }) => {
  const { t } = useTranslation("settings");
  const query = useCommunityAuthSettings(communityId);
  const update = useUpdateCommunityAuthSettings(communityId);
  const [error, setError] = useState<string | null>(null);

  const saved = query.data;
  if (!saved?.ai_offered_by_platform) return null;

  // Set for this community by whoever runs the server.
  const fixed = saved.set_by_deployment.includes("allow_ai");

  const change = (next: boolean) => {
    setError(null);
    update.mutate(
      { allow_ai: next },
      {
        onSuccess: () => {
          toast.success(t("communityAI.switchSaved"));
          // The AI buttons read whether AI is on here.
          void invalidate(q.resolvedAISettings());
        },
        onError: (err: unknown) =>
          setError(getErrorMessage(err, "settings:communityAI.switchError")),
      }
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("communityAI.switchTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1">
            <Label htmlFor="community-ai" className="font-medium">
              {t("communityAI.switchLabel")}
            </Label>
            <p className="text-muted-foreground text-sm">
              {fixed ? t("communityAuth.setByDeployment") : t("communityAI.switchHelp")}
            </p>
          </div>
          <Switch
            id="community-ai"
            checked={saved.allow_ai}
            onCheckedChange={change}
            disabled={update.isPending || fixed}
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
