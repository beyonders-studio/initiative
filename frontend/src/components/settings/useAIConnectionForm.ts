import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  AIConnectionCommunity,
  AIConnectionCreate,
  AIConnectionResponse,
  AIConnectionUpdate,
  AIProvider,
  ConnectionScope,
} from "@/api/generated/initiativeAPI.schemas";
import { useServerForm } from "@/hooks/useServerForm";
import { PROVIDER_CONFIGS } from "@/lib/ai-providers";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";

import type { ConnectionMutations } from "./aiConnection.types";

export interface AIConnectionFormState {
  label: string;
  provider: AIProvider | "";
  baseUrl: string;
  model: string;
  apiKey: string;
  isDefault: boolean;
  communities: AIConnectionCommunity[];
}

const emptyForm: AIConnectionFormState = {
  label: "",
  provider: "",
  baseUrl: "",
  model: "",
  apiKey: "",
  isDefault: false,
  communities: [],
};

const toFormState = (connection: AIConnectionResponse): AIConnectionFormState => ({
  label: connection.label,
  provider: connection.provider,
  baseUrl: connection.base_url ?? "",
  model: connection.model ?? "",
  apiKey: "",
  isDefault: connection.is_default,
  communities: connection.communities,
});

interface UseAIConnectionFormArgs {
  scope: ConnectionScope;
  connection: AIConnectionResponse | null;
  mutations: ConnectionMutations;
  onClose: () => void;
  /** A connection made without a model, to pick one for next. */
  onNeedsModel: (connection: AIConnectionResponse) => void;
}

/**
 * Owns the create/edit connection form: field state, provider-derived field
 * visibility, model fetching, and submit wiring. The dialog stays presentational.
 */
export const useAIConnectionForm = ({
  scope,
  connection,
  mutations,
  onClose,
  onNeedsModel,
}: UseAIConnectionFormArgs) => {
  const { t } = useTranslation("settings");
  const isEdit = connection !== null;
  const serverForm = useServerForm(
    connection ?? undefined,
    (loaded) => (loaded ? toFormState(loaded) : emptyForm),
    connection?.id
  );
  const form = serverForm.values;
  // The models a connection offers belong to the connection, not to the form.
  const [availableModels, setAvailableModels] = useState<string[]>([]);

  const setField = <K extends keyof AIConnectionFormState>(
    key: K,
    value: AIConnectionFormState[K]
  ) => serverForm.set({ [key]: value } as Partial<AIConnectionFormState>);

  const providerConfig = form.provider ? PROVIDER_CONFIGS[form.provider] : null;
  const showApiKeyField = providerConfig?.hasApiKey ?? false;
  const showBaseUrlField = providerConfig?.requiresBaseUrl ?? false;
  const canSave = Boolean(form.provider && form.label);

  const changeProvider = (value: string) => {
    if (!value) return;
    const config = PROVIDER_CONFIGS[value as AIProvider];
    serverForm.set({
      provider: value as AIProvider,
      baseUrl: config?.defaultBaseUrl ?? "",
    });
    setAvailableModels([]);
  };

  const fetchModels = () => {
    // Models come from a saved connection's provider.
    if (!isEdit || !connection || mutations.fetchModels.isPending) return;
    mutations.fetchModels.mutate(connection.id, {
      onSuccess: (data) => {
        if (data.models.length > 0) setAvailableModels(data.models);
      },
    });
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!form.provider || !canSave) return;
    const baseUrl = showBaseUrlField ? form.baseUrl || null : null;

    if (isEdit && connection) {
      const payload: AIConnectionUpdate = {
        label: form.label,
        provider: form.provider,
        base_url: baseUrl,
        model: form.model || null,
        is_default: form.isDefault,
      };
      if (form.apiKey) payload.api_key = form.apiKey;
      if (scope === "platform") payload.community_ids = form.communities.map((c) => c.id);
      mutations.update.mutate(
        { connectionId: connection.id, data: payload },
        {
          onSuccess: (updated) => {
            toast.success(t("aiConnections.updated"));
            // Saved details are what the provider's list is read with; the
            // dialog stays on the model until one is picked.
            if (updated.model) onClose();
            else onNeedsModel(updated);
          },
          onError: (error) =>
            toast.error(getErrorMessage(error, "settings:aiConnections.saveError")),
        }
      );
      return;
    }

    const payload: AIConnectionCreate = {
      label: form.label,
      provider: form.provider,
      base_url: baseUrl,
      model: form.model || null,
      api_key: form.apiKey || null,
      is_default: form.isDefault,
      community_ids: scope === "platform" ? form.communities.map((c) => c.id) : [],
    };
    mutations.create.mutate(payload, {
      onSuccess: (created) => {
        toast.success(t("aiConnections.created"));
        // A saved connection can read its provider's list of models.
        if (created.model) onClose();
        else onNeedsModel(created);
      },
      onError: (error) => toast.error(getErrorMessage(error, "settings:aiConnections.saveError")),
    });
  };

  const isPending = isEdit ? mutations.update.isPending : mutations.create.isPending;

  return {
    form,
    setField,
    isEdit,
    providerConfig,
    showApiKeyField,
    showBaseUrlField,
    modelOptions: availableModels,
    canSave,
    isFetchingModels: mutations.fetchModels.isPending,
    isPending,
    changeProvider,
    fetchModels,
    submit,
  };
};
