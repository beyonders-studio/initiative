import { useTranslation } from "react-i18next";

import type {
  AIConnectionResponse,
  AIProvider,
  ConnectionScope,
} from "@/api/generated/initiativeAPI.schemas";
import { PROVIDER_CONFIGS } from "@/lib/ai-providers";
import { Combobox } from "@/ui/combobox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Switch } from "@/ui/switch";

import { AIConnectionCommunitiesField } from "./AIConnectionCommunitiesField";
import type { ConnectionMutations } from "./aiConnection.types";
import { useAIConnectionForm } from "./useAIConnectionForm";

interface AIConnectionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  scope: ConnectionScope;
  providers: AIProvider[];
  connection: AIConnectionResponse | null;
  mutations: ConnectionMutations;
  onNeedsModel: (connection: AIConnectionResponse) => void;
}

export const AIConnectionDialog = ({
  open,
  onOpenChange,
  scope,
  providers,
  connection,
  mutations,
  onNeedsModel,
}: AIConnectionDialogProps) => {
  const { t } = useTranslation("settings");
  const {
    form,
    setField,
    isEdit,
    providerConfig,
    showApiKeyField,
    showBaseUrlField,
    modelOptions,
    canSave,
    isFetchingModels,
    isPending,
    changeProvider,
    fetchModels,
    submit,
  } = useAIConnectionForm({
    open,
    scope,
    connection,
    mutations,
    onClose: () => onOpenChange(false),
    onNeedsModel,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {isEdit ? t("aiConnections.editTitle") : t("aiConnections.newTitle")}
          </DialogTitle>
          <DialogDescription>
            {scope === "platform"
              ? t("aiConnections.platformDialogDescription")
              : t("aiConnections.communityDialogDescription")}
          </DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={submit}>
          <Field label={t("aiConnections.labelLabel")}>
            <Input
              value={form.label}
              required
              onChange={(event) => setField("label", event.target.value)}
              placeholder={t("aiConnections.labelPlaceholder")}
            />
          </Field>

          <Field
            label={t("ai.providerFieldLabel")}
            hint={form.provider === "custom" && t("aiConnections.customHint")}
          >
            <Select value={form.provider} onValueChange={changeProvider}>
              <SelectTrigger>
                <SelectValue placeholder={t("ai.providerPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {providers.map((key) => (
                  <SelectItem key={key} value={key}>
                    {PROVIDER_CONFIGS[key].label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          {showApiKeyField && (
            <Field
              label={t("ai.apiKeyLabel")}
              hint={
                connection?.has_api_key
                  ? t("aiConnections.apiKeyHelpExisting")
                  : t("aiConnections.apiKeyHelpNew")
              }
            >
              <Input
                type="password"
                value={form.apiKey}
                onChange={(event) => setField("apiKey", event.target.value)}
                placeholder={
                  connection?.has_api_key
                    ? t("aiConnections.apiKeyPlaceholderExisting")
                    : t("aiConnections.apiKeyPlaceholderNew")
                }
              />
            </Field>
          )}

          {showBaseUrlField && (
            <div className="space-y-2">
              <Label htmlFor="ai-connection-base-url">{t("ai.baseUrlLabel")}</Label>
              <Input
                id="ai-connection-base-url"
                value={form.baseUrl}
                onChange={(event) => setField("baseUrl", event.target.value)}
                placeholder={providerConfig?.defaultBaseUrl ?? "https://api.example.com/v1"}
              />
              {form.provider === "ollama" &&
                form.baseUrl.trim().toLowerCase().startsWith("http://") && (
                  <p className="text-sm text-yellow-600 dark:text-yellow-500">
                    {t("ai.httpWarning")}
                  </p>
                )}
            </div>
          )}

          {form.provider && (
            <Field
              label={t("ai.modelLabel")}
              hint={
                !form.model &&
                (isEdit ? t("aiConnections.modelHintPick") : t("aiConnections.modelHintNew"))
              }
            >
              <Combobox
                items={modelOptions.map((model) => ({ value: model, label: model }))}
                value={form.model}
                selectedLabel={form.model}
                onValueChange={(value) => setField("model", value)}
                placeholder={t("aiConnections.modelPlaceholder")}
                searchPlaceholder={t("aiConnections.modelSearchPlaceholder")}
                loadingLabel={t("aiConnections.modelsLoading")}
                emptyMessage={t("aiConnections.modelsEmpty")}
                typedLabel={(value) => t("aiConnections.modelUseTyped", { value })}
                onOpenChange={(open) => {
                  if (open) fetchModels();
                }}
                // The models already listed stay listed while they are looked up again.
                loading={isFetchingModels && modelOptions.length === 0}
              />
            </Field>
          )}

          {scope === "platform" && (
            <AIConnectionCommunitiesField
              communities={form.communities}
              onChange={(communities) => setField("communities", communities)}
            />
          )}

          <div className="flex items-center justify-between rounded-md border px-4 py-3">
            <div>
              <p className="font-medium">{t("aiConnections.defaultLabel")}</p>
              <p className="text-muted-foreground text-sm">
                {t("aiConnections.defaultDescription")}
              </p>
            </div>
            <Switch
              checked={form.isDefault}
              onCheckedChange={(checked) => setField("isDefault", Boolean(checked))}
            />
          </div>

          <DialogFooter
            submitLabel={t("aiConnections.save")}
            pending={isPending}
            pendingLabel={t("aiConnections.saving")}
            disabled={!canSave}
          />
        </form>
      </DialogContent>
    </Dialog>
  );
};
