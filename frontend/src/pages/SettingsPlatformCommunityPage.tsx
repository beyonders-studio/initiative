/**
 * The community-directory switch (platform settings → Community).
 *
 * One decision, and it belongs to the platform owner rather than to any community:
 * whether this deployment has a community directory at all. Communities decide
 * whether to be *in* it from their own settings page; this decides whether it
 * exists for them to be in.
 *
 * The current value comes from the SPA's boot config rather than a settings
 * read, because it is the same value every other page reads to decide whether
 * to offer the directory — there is one source, not an owner's copy and
 * everyone else's.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { CommunitySettingsResponse, DmPolicy } from "@/api/generated/initiativeAPI.schemas";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useServerForm } from "@/hooks/useServerForm";
import { useCommunitySettings, useUpdateCommunitySettings } from "@/hooks/useSettings";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";
import { readOptionalWholeNumber } from "@/lib/text";
import { ConfirmDialog } from "@/ui/confirm-dialog";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Switch } from "@/ui/switch";

/** The most days the server takes for the longest guest stay. */
const MAX_GUEST_DAYS = 3650;
/** The most communities a day the server takes for one account. */
const MAX_CREATION_DAILY_LIMIT = 1000;
/** The most hours the server takes between two exports of a community: a year. */
const MAX_EXPORT_COOLDOWN_HOURS = 8760;
/** The most days the server takes for a deletion or retention window. */
const MAX_WINDOW_DAYS = 3650;

/** The figures this page changes in a dialog, by the setting each one writes. */
type NumberRule = keyof Pick<
  CommunitySettingsResponse,
  | "max_guest_days"
  | "community_creation_daily_limit"
  | "community_export_cooldown_hours"
  | "deleted_community_retention_days"
  | "on_hold_community_deletion_days"
  | "deleted_account_retention_days"
>;

/** How one figure reads, and the bounds it is held to. */
interface NumberRuleCopy {
  /** The row's label and the dialog's title. */
  label: string;
  description: string;
  fieldLabel: string;
  placeholder?: string;
  hint?: (value: number | null) => string;
  min: number;
  max: number;
  /** Whether a blank box is an answer: never, rather than nothing typed. */
  blank: boolean;
  /** The row's value. */
  value: (value: number | null) => string;
  /** What saving it says. */
  saved: (value: number | null) => string;
}

/** One figure, changed in a dialog. Each opening starts from what is saved. */
const NumberRuleDialog = ({
  rule,
  saved,
  pending,
  onSave,
  open,
  onOpenChange,
}: {
  rule: NumberRuleCopy;
  saved: number | null;
  pending: boolean;
  onSave: (value: number | null) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) => {
  const { t } = useTranslation("common");
  const form = useServerForm(
    saved,
    (loaded) => ({ text: loaded == null ? "" : String(loaded) }),
    open
  );
  const { value, valid } = readOptionalWholeNumber(form.values.text, rule.min, rule.max);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{rule.label}</DialogTitle>
          <DialogDescription>{rule.description}</DialogDescription>
        </DialogHeader>
        <Field label={rule.fieldLabel} hint={rule.hint?.(value)}>
          <Input
            type="number"
            min={rule.min}
            max={rule.max}
            className="w-40"
            value={form.values.text}
            placeholder={rule.placeholder}
            onChange={(event) => form.set({ text: event.target.value })}
          />
        </Field>
        <DialogFooter
          submitLabel={t("save")}
          pending={pending}
          disabled={!valid || (value === null && !rule.blank) || value === saved}
          onSubmit={() => onSave(value)}
        />
      </DialogContent>
    </Dialog>
  );
};

export const SettingsPlatformCommunityPage = () => {
  const { t } = useTranslation(["settings", "common"]);
  const { user } = useAuth();
  const canManagePlatformConfig = hasCapability(user, Capability.configManage);
  const {
    communityDirectoryEnabled,
    communityAgeGateEnabled,
    directMessagesEnabled,
    guestsEnabled,
    isLoading,
  } = useAppConfig();
  const { data: community } = useCommunitySettings();
  const [changing, setChanging] = useState<NumberRule | null>(null);

  // The three windows are each the deployment's, one answer for everybody on
  // the server. Blank means never: nothing happens on a timer, and whatever
  // the window governs waits for somebody to act on it.
  const windowRule = (
    key: "community.retention" | "community.holdDeletion" | "community.accountRetention"
  ): NumberRuleCopy => ({
    label: t(`${key}.title`),
    description: t(`${key}.description`),
    fieldLabel: t(`${key}.label`),
    placeholder: t(`${key}.placeholder`),
    hint: (value) => (value === null ? t(`${key}.neverHint`) : t(`${key}.hint`)),
    min: 1,
    max: MAX_WINDOW_DAYS,
    blank: true,
    value: (value) =>
      value === null ? t(`${key}.placeholder`) : t("settingsSection.days", { count: value }),
    saved: (value) =>
      value === null ? t(`${key}.savedNever`) : t(`${key}.saved`, { count: value }),
  });
  const numberRules: Record<NumberRule, NumberRuleCopy> = {
    // Each community may set a shorter longest stay of its own.
    max_guest_days: {
      label: t("community.maxGuestDaysTitle"),
      description: t("community.maxGuestDaysHelpText"),
      fieldLabel: t("community.maxGuestDaysLabel"),
      min: 1,
      max: MAX_GUEST_DAYS,
      blank: false,
      value: (value) => t("settingsSection.days", { count: value ?? 0 }),
      saved: (value) => t("community.maxGuestDaysSaved", { count: value ?? 0 }),
    },
    // 0 is a figure here, not a blank: it means no limit, and no wait.
    community_creation_daily_limit: {
      label: t("community.creationDailyLimitTitle"),
      description: t("community.creationDailyLimitHelpText"),
      fieldLabel: t("community.creationDailyLimitLabel"),
      min: 0,
      max: MAX_CREATION_DAILY_LIMIT,
      blank: false,
      value: (value) =>
        value ? t("community.creationDailyLimitValue", { count: value }) : t("community.noLimit"),
      saved: (value) =>
        value
          ? t("community.creationDailyLimitSaved", { count: value })
          : t("community.creationDailyLimitSavedNone"),
    },
    community_export_cooldown_hours: {
      label: t("community.exportCooldownTitle"),
      description: t("community.exportCooldownHelpText"),
      fieldLabel: t("community.exportCooldownLabel"),
      min: 0,
      max: MAX_EXPORT_COOLDOWN_HOURS,
      blank: false,
      value: (value) =>
        value ? t("settingsSection.hours", { count: value }) : t("community.noWait"),
      saved: (value) =>
        value
          ? t("community.exportCooldownSaved", { count: value })
          : t("community.exportCooldownSavedNone"),
    },
    // Deleted, not destroyed: once a hold runs out the community waits out
    // the retention window like any other, so an operator can still put it
    // back.
    deleted_community_retention_days: windowRule("community.retention"),
    on_hold_community_deletion_days: windowRule("community.holdDeletion"),
    // What a deployment owes the people in a community and what it owes the
    // person leaving are different questions, and the answer to the second is
    // usually shorter.
    deleted_account_retention_days: windowRule("community.accountRetention"),
  };
  // Turning the age gate off is an assertion about every account here, not a
  // preference, so it is confirmed. Turning it back on is not.
  const [confirmingAgeGateOff, setConfirmingAgeGateOff] = useState(false);
  // And the same for messaging: off takes a feature away from everybody using
  // it, so it is confirmed. On is just giving it back.
  const [confirmingMessagesOff, setConfirmingMessagesOff] = useState(false);

  const update = useUpdateCommunitySettings({
    // One endpoint, many decisions, so the write says which one it was: a
    // reader who just switched messaging off is owed a word about messaging,
    // not about the directory they did not touch.
    onSuccess: (result, variables) => {
      const figure = (Object.keys(numberRules) as NumberRule[]).find(
        (field) => variables[field] !== undefined
      );
      if (figure) {
        toast.success(numberRules[figure].saved(result[figure]));
        setChanging(null);
        return;
      }
      if (variables.direct_messages_enabled !== undefined) {
        toast.success(
          result.direct_messages_enabled
            ? t("community.directMessagesEnabledToast")
            : t("community.directMessagesDisabledToast")
        );
        return;
      }
      if (variables.guests_enabled !== undefined) {
        toast.success(
          result.guests_enabled
            ? t("community.guestsEnabledToast")
            : t("community.guestsDisabledToast")
        );
        return;
      }
      if (variables.public_registration_enabled !== undefined) {
        toast.success(
          result.public_registration_enabled
            ? t("community.publicRegistrationEnabledToast")
            : t("community.publicRegistrationDisabledToast")
        );
        return;
      }
      if (variables.community_creation_enabled !== undefined) {
        toast.success(
          result.community_creation_enabled
            ? t("community.communityCreationEnabledToast")
            : t("community.communityCreationDisabledToast")
        );
        return;
      }
      if (variables.engagement_ranking_enabled !== undefined) {
        toast.success(
          result.engagement_ranking_enabled
            ? t("community.engagementRankingEnabledToast")
            : t("community.engagementRankingDisabledToast")
        );
        return;
      }
      toast.success(
        result.community_directory_enabled
          ? t("community.enabledToast")
          : t("community.disabledToast")
      );
    },
  });

  if (!canManagePlatformConfig) {
    return <p className="text-muted-foreground text-sm">{t("community.platformOnly")}</p>;
  }

  /**
   * A figure's row: its value, and Change. Under a switch that is off, the
   * value is stated with why it waits, and nothing is offered.
   */
  const figureRow = (field: NumberRule, offNote?: string | false) =>
    community ? (
      <SettingsRow
        label={numberRules[field].label}
        value={numberRules[field].value(community[field])}
        description={offNote || undefined}
        onChange={offNote ? undefined : () => setChanging(field)}
      />
    ) : null;

  return (
    <SettingsSection title={t("community.title")} description={t("community.description")}>
      <SettingsRow
        label={t("community.toggleLabel")}
        description={t("community.helpText")}
        below={
          // Turning it back off is not a punishment for the communities that
          // opted in, and saying so up front stops it reading like one.
          <p className="text-muted-foreground text-xs">{t("community.reversibleNote")}</p>
        }
      >
        <Switch
          checked={communityDirectoryEnabled}
          disabled={isLoading || update.isPending}
          onCheckedChange={(checked) =>
            update.mutate({ community_directory_enabled: Boolean(checked) })
          }
        />
      </SettingsRow>

      {/* The second switch. Shown regardless of the first, so an owner can
          settle it before opening the directory rather than discovering it
          once people are already arriving. */}
      <SettingsRow label={t("community.ageGateLabel")} description={t("community.ageGateHelpText")}>
        <Switch
          checked={communityAgeGateEnabled}
          disabled={isLoading || update.isPending}
          onCheckedChange={(checked) => {
            if (checked) {
              update.mutate({
                community_directory_enabled: communityDirectoryEnabled,
                age_gate_enabled: true,
              });
              return;
            }
            setConfirmingAgeGateOff(true);
          }}
        />
      </SettingsRow>

      {/* The third switch, and the only one here that is not about the
          directory: a deployment can run one without messaging, or messaging
          without one. */}
      <SettingsRow
        label={t("community.directMessagesLabel")}
        description={t("community.directMessagesHelpText")}
        below={
          <>
            {/* Nothing is deleted while it is off, and an owner weighing the
                switch is entitled to know that before they touch it rather
                than after. */}
            <p className="text-muted-foreground text-xs">
              {t("community.directMessagesReversibleNote")}
            </p>

            {/* Read once, when an account is made, so changing it moves nobody
                who is already here. Nested under the switch because it is a
                question about messaging: with messaging off there is no policy
                to start anybody on, so the row goes quiet, stating the policy
                rather than offering it, and does not disappear. */}
            {community ? (
              <div className="ms-7 border-s ps-4">
                {directMessagesEnabled ? (
                  <SettingsRow
                    label={t("community.defaultDmLabel")}
                    description={t("community.defaultDmHelpText")}
                  >
                    <Select
                      value={community.default_dm_policy}
                      disabled={isLoading || update.isPending}
                      onValueChange={(value) =>
                        update.mutate({
                          community_directory_enabled: communityDirectoryEnabled,
                          default_dm_policy: value as DmPolicy,
                        })
                      }
                    >
                      <SelectTrigger className="w-44">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="private">{t("privacy.dm.private")}</SelectItem>
                        <SelectItem value="community">{t("privacy.dm.community")}</SelectItem>
                        <SelectItem value="public">{t("privacy.dm.public")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </SettingsRow>
                ) : (
                  <SettingsRow
                    label={t("community.defaultDmLabel")}
                    value={t(`privacy.dm.${community.default_dm_policy}`)}
                    description={t("community.whileMessagesOff")}
                  />
                )}
              </div>
            ) : null}
          </>
        }
      >
        <Switch
          checked={directMessagesEnabled}
          disabled={isLoading || update.isPending}
          onCheckedChange={(checked) => {
            if (checked) {
              update.mutate({
                community_directory_enabled: communityDirectoryEnabled,
                direct_messages_enabled: true,
              });
              return;
            }
            setConfirmingMessagesOff(true);
          }}
        />
      </SettingsRow>

      <ConfirmDialog
        open={confirmingMessagesOff}
        onOpenChange={setConfirmingMessagesOff}
        title={t("community.directMessagesOffTitle")}
        description={t("community.directMessagesOffBody")}
        confirmLabel={t("community.directMessagesOffConfirm")}
        onConfirm={() =>
          update.mutate({
            community_directory_enabled: communityDirectoryEnabled,
            direct_messages_enabled: false,
          })
        }
      />

      {/* Each community is asked too, and off wins, so this is the most any
          community can have. */}
      <SettingsRow
        label={t("community.engagementRankingLabel")}
        description={t("community.engagementRankingHelpText")}
      >
        <Switch
          checked={community?.engagement_ranking_enabled ?? true}
          disabled={isLoading || update.isPending || !community}
          onCheckedChange={(checked) =>
            update.mutate({
              community_directory_enabled: communityDirectoryEnabled,
              engagement_ranking_enabled: Boolean(checked),
            })
          }
        />
      </SettingsRow>

      {/* Each community may set a shorter longest stay of its own, and may
          take no guests at all. */}
      <SettingsRow
        label={t("community.guestsEnabledLabel")}
        description={t("community.guestsEnabledHelpText")}
        below={
          <div className="ms-7 border-s ps-4">
            {figureRow("max_guest_days", !guestsEnabled && t("community.whileGuestsOff"))}
          </div>
        }
      >
        <Switch
          checked={guestsEnabled}
          disabled={isLoading || update.isPending}
          onCheckedChange={(checked) =>
            update.mutate({
              community_directory_enabled: communityDirectoryEnabled,
              guests_enabled: Boolean(checked),
            })
          }
        />
      </SettingsRow>

      {/* Who may arrive without an invite, and who may start a community
          once here. Registration closes with community creation, so the two
          sit together. */}
      <div className="space-y-4">
        <h3 className="font-semibold text-sm">{t("community.joinAndCreateTitle")}</h3>
        <SettingsRow
          label={t("community.publicRegistrationLabel")}
          description={t("community.publicRegistrationHelpText")}
        >
          <Switch
            checked={community?.public_registration_enabled ?? true}
            disabled={isLoading || update.isPending || !community}
            onCheckedChange={(checked) =>
              update.mutate({
                community_directory_enabled: communityDirectoryEnabled,
                public_registration_enabled: Boolean(checked),
              })
            }
          />
        </SettingsRow>
        <SettingsRow
          label={t("community.communityCreationLabel")}
          description={t("community.communityCreationHelpText")}
          below={
            <div className="ms-7 border-s ps-4">
              {figureRow(
                "community_creation_daily_limit",
                !community?.community_creation_enabled && t("community.whileCreationOff")
              )}
            </div>
          }
        >
          <Switch
            checked={community?.community_creation_enabled ?? true}
            disabled={isLoading || update.isPending || !community}
            onCheckedChange={(checked) =>
              update.mutate({
                community_directory_enabled: communityDirectoryEnabled,
                community_creation_enabled: Boolean(checked),
              })
            }
          />
        </SettingsRow>
      </div>

      {/* What a community may take away with it, and how long what is
          deleted is kept. */}
      <div className="space-y-4">
        <h3 className="font-semibold text-sm">{t("community.exportAndDeletionTitle")}</h3>
        {figureRow("community_export_cooldown_hours")}
        {figureRow("deleted_community_retention_days")}
        {figureRow("on_hold_community_deletion_days")}
        {figureRow("deleted_account_retention_days")}
      </div>

      {community
        ? (Object.keys(numberRules) as NumberRule[]).map((field) => (
            <NumberRuleDialog
              key={field}
              rule={numberRules[field]}
              saved={community[field]}
              pending={update.isPending}
              onSave={(value) =>
                update.mutate({
                  // The endpoint writes the directory switch on every write,
                  // so it is sent back as it stands rather than flipped by a
                  // save about something else.
                  community_directory_enabled: communityDirectoryEnabled,
                  [field]: value,
                })
              }
              open={changing === field}
              onOpenChange={(open) => {
                if (!open) setChanging(null);
              }}
            />
          ))
        : null}

      <ConfirmDialog
        open={confirmingAgeGateOff}
        onOpenChange={setConfirmingAgeGateOff}
        title={t("community.ageGateOffTitle")}
        description={t("community.ageGateOffBody")}
        confirmLabel={t("community.ageGateOffConfirm")}
        onConfirm={() =>
          update.mutate({
            community_directory_enabled: communityDirectoryEnabled,
            age_gate_enabled: false,
          })
        }
      />
    </SettingsSection>
  );
};
