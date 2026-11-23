import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type { IntakeStream } from "@/api/generated/initiativeAPI.schemas";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { useAuth } from "@/hooks/useAuth";
import {
  useIntakeOptions,
  useIntakeSettings,
  useUpdateFeedbackSwitch,
  useUpdateIntakeGeneralContact,
  useUpdateOperationsCommunity,
} from "@/hooks/useIntakeSettings";
import { usePlatformCommunities } from "@/hooks/useSettings";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";
import { Button } from "@/ui/button";
import { Combobox } from "@/ui/combobox";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { StatusMessage } from "@/ui/status-message";
import { Switch } from "@/ui/switch";

import { NONE } from "./StreamDialog";
import { StreamRow } from "./StreamRow";

/**
 * Platform → Intake: where each kind of case lands.
 *
 * The operations community comes first, then one row per kind of case with
 * where it lands, who to contact about it and whether it is receiving; each
 * row's dialog holds the rest. Contacts work without a community: a notice
 * names one either way. The switch that sends feedback to the Initiative team
 * is outbound, not intake, so it sits apart at the end.
 */
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
      <SettingsSection
        title={t("community.title")}
        description={t("community.description")}
        contentClassName="space-y-4"
      >
        <Field label={t("community.label")} className="max-w-md">
          <Combobox
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
        </Field>
        {boundCommunityId === null ? (
          <p className="text-muted-foreground text-sm">{t("rows.chooseCommunity")}</p>
        ) : null}

        {settings ? (
          <>
            <ul className="divide-y rounded-md border">
              {settings.bindings.map((binding) => (
                <StreamRow
                  key={binding.stream}
                  binding={binding}
                  contact={settings.contact_emails?.[binding.stream as IntakeStream] ?? ""}
                  routable={boundCommunityId !== null}
                  initiatives={options?.initiatives ?? []}
                  settled={settled}
                />
              ))}
            </ul>
            <GeneralContact
              key={settings.general_contact_email ?? ""}
              saved={settings.general_contact_email ?? ""}
              settled={settled}
            />
          </>
        ) : null}
      </SettingsSection>

      {settings ? <FeedbackCard enabled={settings.feedback_enabled} settled={settled} /> : null}

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

/** The address a notice names for a kind of case with none of its own. */
const GeneralContact = ({ saved, settled }: { saved: string; settled: boolean }) => {
  const { t } = useTranslation("intake");
  const [email, setEmail] = useState(saved);
  const update = useUpdateIntakeGeneralContact();
  const changed = email.trim() !== saved;

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await update.mutateAsync({ email: email.trim() || null });
      toast.success(t("contacts.saved"));
    } catch (err) {
      toast.error(getErrorMessage(err, "intake:contacts.saveError"));
    }
  };

  return (
    <form className="space-y-2" onSubmit={onSubmit}>
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t("contacts.generalLabel")} className="min-w-0 max-w-md grow">
          <Input
            type="email"
            value={email}
            placeholder={t("contacts.generalPlaceholder")}
            disabled={!settled || update.isPending}
            onChange={(event) => setEmail(event.target.value)}
          />
        </Field>
        <Button type="submit" variant="outline" disabled={!settled || update.isPending || !changed}>
          {update.isPending ? t("contacts.saving") : t("contacts.save")}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">{t("contacts.generalHelp")}</p>
    </form>
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
