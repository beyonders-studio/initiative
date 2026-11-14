import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { useAuth } from "@/hooks/useAuth";
import {
  useIntakeOptions,
  useIntakeSettings,
  useUpdateFeedbackSwitch,
  useUpdateOperationsCommunity,
} from "@/hooks/useIntakeSettings";
import { usePlatformCommunities } from "@/hooks/useSettings";
import { Capability, hasCapability } from "@/lib/permissions";
import { Combobox } from "@/ui/combobox";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { Label } from "@/ui/label";
import { StatusMessage } from "@/ui/status-message";
import { Switch } from "@/ui/switch";

import { ContactsCard } from "./ContactsCard";
import { NONE, StreamCard } from "./StreamCard";

export const IntakePage = () => {
  const { t } = useTranslation("intake");
  const { user } = useAuth();
  const isOwner = hasCapability(user, Capability.configManage);

  const {
    data: settings,
    isLoading,
    isFetching: settingsFetching,
    isError: settingsFailed,
    refetch: refetchSettings,
  } = useIntakeSettings({ enabled: isOwner });
  const {
    data: options,
    isFetching: optionsFetching,
    isError: optionsFailed,
    refetch: refetchOptions,
  } = useIntakeOptions({ enabled: isOwner });
  // Searched on the server while the picker is open, rather than every
  // community on the deployment loaded up front.
  const [communitySearch, setCommunitySearch] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const communitiesQuery = usePlatformCommunities(
    { search: communitySearch || undefined, sort_by: "name", page_size: 25 },
    { enabled: isOwner && pickerOpen }
  );

  // The two reads describe one community between them — where each stream
  // lands, and what it could land in — so the page acts on both or neither.
  const failed = settingsFailed || optionsFailed;
  const settled = !failed && !settingsFetching && !optionsFetching;

  const [clearing, setClearing] = useState(false);

  const updateCommunity = useUpdateOperationsCommunity();

  if (!isOwner) {
    return <p className="text-muted-foreground text-sm">{t("ownerOnly")}</p>;
  }

  // A read that failed is a different state from a deployment that has
  // configured nothing, and says so. The picker stays out of reach until the
  // current value is known.
  if (failed) {
    return (
      <StatusMessage
        onRetry={() => {
          refetchSettings();
          refetchOptions();
        }}
      />
    );
  }

  const boundCommunityId = settings?.operations_community_id ?? null;

  return (
    <div className="space-y-6">
      {settings ? <FeedbackCard enabled={settings.feedback_enabled} settled={settled} /> : null}
      {settings ? <ContactsCard settings={settings} settled={settled} /> : null}

      <SettingsSection
        title={t("community.title")}
        description={t("community.description")}
        contentClassName="space-y-3"
      >
        <Label>{t("community.label")}</Label>
        <Combobox
          className="max-w-md"
          aria-label={t("community.label")}
          value={boundCommunityId === null ? NONE : String(boundCommunityId)}
          selectedLabel={
            boundCommunityId === null
              ? t("community.none")
              : (settings?.operations_community_name ?? null)
          }
          items={[
            { value: NONE, label: t("community.none") },
            ...(communitiesQuery.data?.items ?? []).map((community) => ({
              value: String(community.id),
              label: community.name,
            })),
          ]}
          onSearchChange={setCommunitySearch}
          onOpenChange={setPickerOpen}
          loading={communitiesQuery.isFetching}
          placeholder={t("community.placeholder")}
          disabled={isLoading || !settled || updateCommunity.isPending}
          onValueChange={(value) => {
            // Clearing it stops every stream at once, so it is confirmed;
            // choosing a different one is an ordinary change.
            if (value === NONE) {
              setClearing(true);
              return;
            }
            updateCommunity.mutate({ community_id: Number(value) });
          }}
        />
        <p className="text-muted-foreground text-sm">{t("community.helpText")}</p>
      </SettingsSection>

      {boundCommunityId === null ? (
        <p className="text-muted-foreground text-sm">{t("streams.chooseCommunityFirst")}</p>
      ) : (
        <div className="space-y-4">
          {(settings?.bindings ?? []).map((binding) => (
            <StreamCard
              key={binding.stream}
              binding={binding}
              initiatives={options?.initiatives ?? []}
              settled={settled}
            />
          ))}
        </div>
      )}

      <ConfirmDialog
        open={clearing}
        onOpenChange={setClearing}
        title={t("community.clearTitle")}
        description={t("community.clearBody")}
        confirmLabel={t("community.clearConfirm")}
        onConfirm={() => updateCommunity.mutate({ community_id: null })}
      />
    </div>
  );
};

/** Whether people here may send feedback to the Initiative team. */
const FeedbackCard = ({ enabled, settled }: { enabled: boolean; settled: boolean }) => {
  const { t } = useTranslation("intake");
  const update = useUpdateFeedbackSwitch();
  return (
    <SettingsSection
      title={t("feedbackSwitch.title")}
      description={t("feedbackSwitch.description")}
    >
      <SettingsRow label={t("feedbackSwitch.label")}>
        <Switch
          checked={enabled}
          disabled={!settled || update.isPending}
          onCheckedChange={(checked) => update.mutate({ enabled: checked })}
        />
      </SettingsRow>
    </SettingsSection>
  );
};
