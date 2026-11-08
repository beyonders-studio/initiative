import { useTranslation } from "react-i18next";

import {
  useGetPlatformAiMode,
  useListPlatformConnections,
} from "@/api/generated/ai-settings/ai-settings";
import type { AIConfigMode } from "@/api/generated/initiativeAPI.schemas";
import {
  AIConnectionManager,
  type ConnectionMutations,
} from "@/components/settings/AIConnectionManager";
import {
  useCreatePlatformConnection,
  useDeletePlatformConnection,
  useFetchPlatformConnectionModels,
  useTestPlatformConnection,
  useUpdatePlatformAIMode,
  useUpdatePlatformConnection,
} from "@/hooks/useAISettings";
import { useAuth } from "@/hooks/useAuth";
import { useServerForm } from "@/hooks/useServerForm";
import { getProvidersForScope } from "@/lib/ai-providers";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { Label } from "@/ui/label";
import { FormSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";
import { StatusMessage } from "@/ui/status-message";

const MODES: AIConfigMode[] = ["disabled", "platform", "community"];

export const SettingsAIPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const isPlatformOwner = hasCapability(user, Capability.configManage);

  const modeQuery = useGetPlatformAiMode({ query: { enabled: isPlatformOwner } });
  // Chosen, then saved: a refetch in between must not put the old mode back.
  const form = useServerForm(
    modeQuery.data,
    (settings) => ({
      mode: settings?.mode ?? ("disabled" as AIConfigMode),
    }),
    "platform-ai"
  );
  const mode = form.values.mode;
  const setMode = (next: AIConfigMode) => form.set({ mode: next });

  const updateMode = useUpdatePlatformAIMode({
    onSuccess: () => toast.success(t("platformAI.modeSaved")),
  });

  const savedMode = modeQuery.data?.mode;
  const connectionsQuery = useListPlatformConnections({
    query: { enabled: isPlatformOwner && savedMode === "platform" },
  });

  const mutations: ConnectionMutations = {
    create: useCreatePlatformConnection(),
    update: useUpdatePlatformConnection(),
    remove: useDeletePlatformConnection(),
    test: useTestPlatformConnection(),
    fetchModels: useFetchPlatformConnectionModels(),
  };

  if (!isPlatformOwner) {
    return <p className="text-muted-foreground text-sm">{t("platformAI.platformOnly")}</p>;
  }

  if (modeQuery.isLoading) {
    return (
      <SkeletonRegion label={t("ai.loading")}>
        <FormSkeleton fields={2} />
      </SkeletonRegion>
    );
  }

  if (modeQuery.isError || !modeQuery.data) {
    return <StatusMessage onRetry={modeQuery.refetch} />;
  }

  const isDirty = mode !== modeQuery.data.mode;

  const handleSave = () => {
    // What is being sent, so a mode picked while this is in flight is not
    // counted as saved by it.
    const sent = form.values;
    updateMode.mutate({ mode: sent.mode }, { onSuccess: () => form.settle(sent) });
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("platformAI.title")}</CardTitle>
          <CardDescription>{t("platformAI.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <fieldset className="space-y-3">
            <legend className="font-medium text-sm">{t("platformAI.modeLabel")}</legend>
            <RadioGroup value={mode} onValueChange={(value) => setMode(value as AIConfigMode)}>
              {MODES.map((value) => (
                <Label
                  key={value}
                  htmlFor={`ai-mode-${value}`}
                  className="flex cursor-pointer items-start gap-3 rounded-md border px-4 py-3 font-normal has-[:checked]:border-primary"
                >
                  <RadioGroupItem id={`ai-mode-${value}`} value={value} className="mt-0.5" />
                  <span className="space-y-1">
                    <span className="block font-medium">{t(`platformAI.mode_${value}`)}</span>
                    <span className="block text-muted-foreground text-sm">
                      {t(`platformAI.mode_${value}_description`)}
                    </span>
                  </span>
                </Label>
              ))}
            </RadioGroup>
          </fieldset>

          <Button type="button" onClick={handleSave} disabled={updateMode.isPending || !isDirty}>
            {updateMode.isPending ? t("platformAI.savingMode") : t("platformAI.saveMode")}
          </Button>
        </CardContent>
      </Card>

      {savedMode === "platform" && (
        <Card>
          <CardContent className="pt-6">
            <AIConnectionManager
              scope="platform"
              connections={connectionsQuery.data ?? []}
              isLoading={connectionsQuery.isLoading}
              isError={connectionsQuery.isError}
              providers={getProvidersForScope("platform")}
              mutations={mutations}
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
};
