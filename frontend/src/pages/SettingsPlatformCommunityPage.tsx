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

import type { DmPolicy } from "@/api/generated/initiativeAPI.schemas";
import { DeletedAccountRetentionSection } from "@/components/platform/DeletedAccountRetentionSection";
import { DeletedCommunityRetentionSection } from "@/components/platform/DeletedCommunityRetentionSection";
import { OnHoldCommunityDeletionSection } from "@/components/platform/OnHoldCommunityDeletionSection";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useServerForm } from "@/hooks/useServerForm";
import { useCommunitySettings, useUpdateCommunitySettings } from "@/hooks/useSettings";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";
import { readOptionalWholeNumber } from "@/lib/text";

/** The most days the server takes for the longest guest stay. */
const MAX_GUEST_DAYS = 3650;
/** The most communities a day the server takes for one account. */
const MAX_CREATION_DAILY_LIMIT = 1000;
/** The most hours the server takes between two exports of a community: a year. */
const MAX_EXPORT_COOLDOWN_HOURS = 8760;

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
  // Typed here and saved by its button, so a refetch does not reset it.
  const guestDaysForm = useServerForm(
    community,
    (loaded) => ({ days: loaded ? String(loaded.max_guest_days) : "" }),
    "max_guest_days"
  );
  const guestDays = readOptionalWholeNumber(guestDaysForm.values.days, 1, MAX_GUEST_DAYS);
  // 0 is a figure here, not a blank: it means no limit, and no wait.
  const creationLimitForm = useServerForm(
    community,
    (loaded) => ({ count: loaded ? String(loaded.community_creation_daily_limit) : "" }),
    "community_creation_daily_limit"
  );
  const creationLimit = readOptionalWholeNumber(
    creationLimitForm.values.count,
    0,
    MAX_CREATION_DAILY_LIMIT
  );
  const exportCooldownForm = useServerForm(
    community,
    (loaded) => ({ hours: loaded ? String(loaded.community_export_cooldown_hours) : "" }),
    "community_export_cooldown_hours"
  );
  const exportCooldown = readOptionalWholeNumber(
    exportCooldownForm.values.hours,
    0,
    MAX_EXPORT_COOLDOWN_HOURS
  );
  // Turning the age gate off is an assertion about every account here, not a
  // preference, so it is confirmed. Turning it back on is not.
  const [confirmingAgeGateOff, setConfirmingAgeGateOff] = useState(false);
  // And the same for messaging: off takes a feature away from everybody using
  // it, so it is confirmed. On is just giving it back.
  const [confirmingMessagesOff, setConfirmingMessagesOff] = useState(false);

  const update = useUpdateCommunitySettings({
    // One endpoint, four decisions, so the write says which one it was: a
    // reader who just switched messaging off is owed a word about messaging,
    // not about the directory they did not touch.
    onSuccess: (result, variables) => {
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
      if (variables.max_guest_days !== undefined) {
        guestDaysForm.settle({ days: String(variables.max_guest_days) });
        toast.success(t("community.maxGuestDaysSaved", { count: result.max_guest_days }));
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
      if (variables.community_creation_daily_limit !== undefined) {
        creationLimitForm.settle({ count: String(variables.community_creation_daily_limit) });
        toast.success(
          result.community_creation_daily_limit === 0
            ? t("community.creationDailyLimitSavedNone")
            : t("community.creationDailyLimitSaved", {
                count: result.community_creation_daily_limit,
              })
        );
        return;
      }
      if (variables.community_export_cooldown_hours !== undefined) {
        exportCooldownForm.settle({ hours: String(variables.community_export_cooldown_hours) });
        toast.success(
          result.community_export_cooldown_hours === 0
            ? t("community.exportCooldownSavedNone")
            : t("community.exportCooldownSaved", {
                count: result.community_export_cooldown_hours,
              })
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
    onError: (err) => {
      toast.error(getErrorMessage(err, "settings:community.saveError"));
    },
  });

  if (!canManagePlatformConfig) {
    return <p className="text-muted-foreground text-sm">{t("community.platformOnly")}</p>;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("community.title")}</CardTitle>
        <CardDescription>{t("community.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-3">
          <Switch
            id="community-directory-enabled"
            checked={communityDirectoryEnabled}
            disabled={isLoading || update.isPending}
            onCheckedChange={(checked) =>
              update.mutate({ community_directory_enabled: Boolean(checked) })
            }
          />
          <Label htmlFor="community-directory-enabled">{t("community.toggleLabel")}</Label>
        </div>
        <p className="text-muted-foreground text-sm">{t("community.helpText")}</p>
        {/* Turning it back off is not a punishment for the communities that opted
            in, and saying so up front stops it reading like one. */}
        <p className="text-muted-foreground text-xs">{t("community.reversibleNote")}</p>

        {/* The second switch. Shown regardless of the first, so an owner can
            settle it before opening the directory rather than discovering it
            once people are already arriving. */}
        <div className="space-y-4 border-t pt-4">
          <div className="flex items-center gap-3">
            <Switch
              id="community-age-gate-enabled"
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
            <Label htmlFor="community-age-gate-enabled">{t("community.ageGateLabel")}</Label>
          </div>
          <p className="text-muted-foreground text-sm">{t("community.ageGateHelpText")}</p>
        </div>

        {/* The third switch, and the only one here that is not about the
            directory: a deployment can run one without messaging, or messaging
            without one. */}
        <div className="space-y-4 border-t pt-4">
          <div className="flex items-center gap-3">
            <Switch
              id="direct-messages-enabled"
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
            <Label htmlFor="direct-messages-enabled">{t("community.directMessagesLabel")}</Label>
          </div>
          <p className="text-muted-foreground text-sm">{t("community.directMessagesHelpText")}</p>
          {/* Nothing is deleted while it is off, and an owner weighing the
              switch is entitled to know that before they touch it rather than
              after. */}
          <p className="text-muted-foreground text-xs">
            {t("community.directMessagesReversibleNote")}
          </p>

          {/* Read once, when an account is made, so changing it moves nobody
              who is already here. Nested under the switch because it is a
              question about messaging: with messaging off there is no policy
              to start anybody on, and the control says so by going quiet
              rather than disappearing. */}
          <div className="ms-7 space-y-2 border-s ps-4">
            <Label htmlFor="default-dm-policy">{t("community.defaultDmLabel")}</Label>
            <Select
              value={community?.default_dm_policy ?? "private"}
              disabled={isLoading || update.isPending || !community || !directMessagesEnabled}
              onValueChange={(value) =>
                update.mutate({
                  community_directory_enabled: communityDirectoryEnabled,
                  default_dm_policy: value as DmPolicy,
                })
              }
            >
              <SelectTrigger id="default-dm-policy" className="max-w-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="private">{t("privacy.dm.private")}</SelectItem>
                <SelectItem value="community">{t("privacy.dm.community")}</SelectItem>
                <SelectItem value="public">{t("privacy.dm.public")}</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-sm">{t("community.defaultDmHelpText")}</p>
          </div>
        </div>

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
        <div className="space-y-4 border-t pt-4">
          <div className="flex items-center gap-3">
            <Switch
              id="engagement-ranking-enabled"
              checked={community?.engagement_ranking_enabled ?? true}
              disabled={isLoading || update.isPending || !community}
              onCheckedChange={(checked) =>
                update.mutate({
                  community_directory_enabled: communityDirectoryEnabled,
                  engagement_ranking_enabled: Boolean(checked),
                })
              }
            />
            <Label htmlFor="engagement-ranking-enabled">
              {t("community.engagementRankingLabel")}
            </Label>
          </div>
          <p className="text-muted-foreground text-sm">
            {t("community.engagementRankingHelpText")}
          </p>
        </div>

        {/* Each community may set a shorter longest stay of its own, and may
            take no guests at all. */}
        <div className="space-y-4 border-t pt-4">
          <div className="flex items-center gap-3">
            <Switch
              id="guests-enabled"
              checked={guestsEnabled}
              disabled={isLoading || update.isPending}
              onCheckedChange={(checked) =>
                update.mutate({
                  community_directory_enabled: communityDirectoryEnabled,
                  guests_enabled: Boolean(checked),
                })
              }
            />
            <Label htmlFor="guests-enabled">{t("community.guestsEnabledLabel")}</Label>
          </div>
          <p className="text-muted-foreground text-sm">{t("community.guestsEnabledHelpText")}</p>
          <div className="ms-7 space-y-2 border-s ps-4">
            <Label htmlFor="max-guest-days">{t("community.maxGuestDaysLabel")}</Label>
            <div className="flex flex-wrap items-center gap-3">
              <Input
                id="max-guest-days"
                type="number"
                min={1}
                max={MAX_GUEST_DAYS}
                className="w-40"
                value={guestDaysForm.values.days}
                disabled={!community || !guestsEnabled}
                onChange={(event) => guestDaysForm.set({ days: event.target.value })}
              />
              <Button
                aria-label={t("community.maxGuestDaysSave")}
                disabled={
                  !community ||
                  !guestsEnabled ||
                  guestDays.value === null ||
                  !guestDays.valid ||
                  guestDays.value === community.max_guest_days ||
                  update.isPending
                }
                onClick={() =>
                  update.mutate({
                    community_directory_enabled: communityDirectoryEnabled,
                    max_guest_days: guestDays.value,
                  })
                }
              >
                {update.isPending ? t("common:submitting") : t("common:save")}
              </Button>
            </div>
            <p className="text-muted-foreground text-sm">{t("community.maxGuestDaysHelpText")}</p>
          </div>
        </div>

        {/* Who may arrive without an invite, and who may start a community
            once here. Registration closes with community creation, so the two
            sit together. */}
        <div className="space-y-4 border-t pt-4">
          <h3 className="font-semibold text-sm">{t("community.joinAndCreateTitle")}</h3>
          <div className="flex items-center gap-3">
            <Switch
              id="public-registration-enabled"
              checked={community?.public_registration_enabled ?? true}
              disabled={isLoading || update.isPending || !community}
              onCheckedChange={(checked) =>
                update.mutate({
                  community_directory_enabled: communityDirectoryEnabled,
                  public_registration_enabled: Boolean(checked),
                })
              }
            />
            <Label htmlFor="public-registration-enabled">
              {t("community.publicRegistrationLabel")}
            </Label>
          </div>
          <p className="text-muted-foreground text-sm">
            {t("community.publicRegistrationHelpText")}
          </p>
          <div className="flex items-center gap-3">
            <Switch
              id="community-creation-enabled"
              checked={community?.community_creation_enabled ?? true}
              disabled={isLoading || update.isPending || !community}
              onCheckedChange={(checked) =>
                update.mutate({
                  community_directory_enabled: communityDirectoryEnabled,
                  community_creation_enabled: Boolean(checked),
                })
              }
            />
            <Label htmlFor="community-creation-enabled">
              {t("community.communityCreationLabel")}
            </Label>
          </div>
          <p className="text-muted-foreground text-sm">
            {t("community.communityCreationHelpText")}
          </p>
          <div className="ms-7 space-y-2 border-s ps-4">
            <Label htmlFor="community-creation-daily-limit">
              {t("community.creationDailyLimitLabel")}
            </Label>
            <div className="flex flex-wrap items-center gap-3">
              <Input
                id="community-creation-daily-limit"
                type="number"
                min={0}
                max={MAX_CREATION_DAILY_LIMIT}
                className="w-40"
                value={creationLimitForm.values.count}
                disabled={!community?.community_creation_enabled}
                onChange={(event) => creationLimitForm.set({ count: event.target.value })}
              />
              <Button
                aria-label={t("community.creationDailyLimitSave")}
                disabled={
                  !community?.community_creation_enabled ||
                  creationLimit.value === null ||
                  !creationLimit.valid ||
                  creationLimit.value === community.community_creation_daily_limit ||
                  update.isPending
                }
                onClick={() =>
                  update.mutate({
                    community_directory_enabled: communityDirectoryEnabled,
                    community_creation_daily_limit: creationLimit.value,
                  })
                }
              >
                {update.isPending ? t("common:submitting") : t("common:save")}
              </Button>
            </div>
            <p className="text-muted-foreground text-sm">
              {t("community.creationDailyLimitHelpText")}
            </p>
          </div>
        </div>

        <div className="space-y-2 border-t pt-4">
          <Label htmlFor="community-export-cooldown">{t("community.exportCooldownLabel")}</Label>
          <div className="flex flex-wrap items-center gap-3">
            <Input
              id="community-export-cooldown"
              type="number"
              min={0}
              max={MAX_EXPORT_COOLDOWN_HOURS}
              className="w-40"
              value={exportCooldownForm.values.hours}
              disabled={!community}
              onChange={(event) => exportCooldownForm.set({ hours: event.target.value })}
            />
            <Button
              aria-label={t("community.exportCooldownSave")}
              disabled={
                !community ||
                exportCooldown.value === null ||
                !exportCooldown.valid ||
                exportCooldown.value === community.community_export_cooldown_hours ||
                update.isPending
              }
              onClick={() =>
                update.mutate({
                  community_directory_enabled: communityDirectoryEnabled,
                  community_export_cooldown_hours: exportCooldown.value,
                })
              }
            >
              {update.isPending ? t("common:submitting") : t("common:save")}
            </Button>
          </div>
          <p className="text-muted-foreground text-sm">{t("community.exportCooldownHelpText")}</p>
        </div>

        <DeletedCommunityRetentionSection directoryEnabled={communityDirectoryEnabled} />

        <OnHoldCommunityDeletionSection directoryEnabled={communityDirectoryEnabled} />

        <DeletedAccountRetentionSection directoryEnabled={communityDirectoryEnabled} />

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
      </CardContent>
    </Card>
  );
};
