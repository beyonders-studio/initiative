import { Link } from "@tanstack/react-router";
import { Bell, ChevronRight, type LucideIcon, Mail, Monitor, Smartphone } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  CategoryGroup,
  type Channel,
  type CommunityNotificationSettings,
  type DigestCadence,
  type DigestScheduleInput,
  type EmailCadence,
  type EmailScheduleInput,
  type NotificationCategory,
  type NotificationCategoryRead,
  type NotificationPreferencesUpdate,
  type UserRead,
} from "@/api/generated/initiativeAPI.schemas";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DateTimePicker } from "@/components/ui/date-time-picker";
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
import {
  useNotificationPreferences,
  useUpdateNotificationPreferences as useWritePreferences,
} from "@/hooks/useNotificationPreferences";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import { useServerForm } from "@/hooks/useServerForm";
import { useFcmConfig } from "@/hooks/useSettings";
import { useUpdateNotificationPreferences } from "@/hooks/useUsers";
import { formatDate } from "@/lib/formatDate";
import { listFormat } from "@/lib/intl";
import { toast } from "@/lib/mascotToast";

// Lead-time presets (minutes) for the event reminder. 0 = "at the time of the
// event"; reminders are turned off with the channel switches, not here.
const REMINDER_MINUTE_OPTIONS = [0, 5, 10, 15, 30, 60, 1440] as const;
const DEFAULT_REMINDER_MINUTES = 15;

// The order the sections appear in, which is the registry's own. The registry
// says which group each category belongs to, so a category added to the
// backend lands in one of these without this file changing. Digests have a
// section of their own, with a schedule beside each.
const GROUP_ORDER = Object.values(CategoryGroup).filter((group) => group !== CategoryGroup.digests);

// Every channel, in column order.
const CHANNELS: Channel[] = ["in_app", "email", "push", "desktop"];

// What names a channel beside its switch where the columns do not fit.
const CHANNEL_ICONS: Record<Channel, LucideIcon> = {
  in_app: Bell,
  email: Mail,
  push: Smartphone,
  desktop: Monitor,
};

// How often email may arrive, in the order the control offers them.
const CADENCES: EmailCadence[] = ["instant", "hourly", "daily", "weekly"];

// How often a digest goes out.
const DIGEST_CADENCES: DigestCadence[] = ["daily", "weekly"];

const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7] as const;

// A pause is booked the way time off is: two days, both of them included. The
// picker hands back a plain "yyyy-MM-dd", which is a day in the reader's own
// clock rather than an instant — so the ends are resolved here, where that
// clock is.
const dayStart = (day: string): string => {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(year, month - 1, date, 0, 0, 0, 0).toISOString();
};

const dayEnd = (day: string): string => {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(year, month - 1, date, 23, 59, 59, 0).toISOString();
};

interface UserSettingsNotificationsPageProps {
  user: UserRead;
  refreshUser: () => Promise<void>;
}

export const UserSettingsNotificationsPage = ({
  user,
  refreshUser,
}: UserSettingsNotificationsPageProps) => {
  const { t, i18n } = useTranslation(["settings", "common"]);
  const { permissionStatus, requestPermission, isSupported } = usePushNotifications();

  const { data: fcmConfig } = useFcmConfig();
  const showPushColumn = fcmConfig?.enabled ?? false;

  const { data: preferences, isLoading } = useNotificationPreferences();
  const writePreferences = useWritePreferences();

  // The lead time the account holds, or the one just picked until its save
  // settles.
  const [pendingReminder, setPendingReminder] = useState<number | null>(null);
  const reminderMinutes =
    pendingReminder ?? user.event_reminder_minutes_before ?? DEFAULT_REMINDER_MINUTES;
  const [pauseFromDay, setPauseFromDay] = useState("");
  const [pauseUntilDay, setPauseUntilDay] = useState("");
  const quietHours = useServerForm(
    preferences?.quiet_hours ?? undefined,
    (saved) => ({ start: saved?.start ?? "22:00", end: saved?.end ?? "07:00" }),
    "quiet-hours"
  );

  const updateSchedule = useUpdateNotificationPreferences();

  // The schedule the server settled on. Read straight off the response rather
  // than mirrored into state: every control here writes and takes the whole
  // document back, so a local copy would only be a second answer to the same
  // question.
  const schedule = preferences?.email;
  const booked = preferences?.pause;
  // A pause booked for next week is shown as booked rather than as running,
  // because those read differently and only one of them is happening.
  const running = booked ? new Date(booked.since) <= new Date() : false;

  const writeTiming = (payload: Parameters<typeof writePreferences.mutate>[0]) =>
    writePreferences.mutate(payload, {
      onError: () => toast.error(t("notifications.timing.saveError")),
    });

  // The schedule is written whole, so each change carries the rest of it.
  const writeEmail = (patch: Partial<EmailScheduleInput>) =>
    writeTiming({
      email: {
        cadence: schedule?.cadence ?? "instant",
        at: schedule?.at ?? "21:00",
        weekday: schedule?.weekday ?? 1,
        personal_instant: schedule?.personal_instant ?? true,
        ...patch,
      },
    });

  // Each digest's schedule is written whole too, and on its own.
  const writeDigest = (category: NotificationCategory, patch: Partial<DigestScheduleInput>) => {
    const current = preferences?.digests?.[category];
    writeTiming({
      digests: {
        [category]: {
          cadence: current?.cadence ?? "daily",
          at: current?.at ?? "21:00",
          weekday: current?.weekday ?? 1,
          ...patch,
        },
      },
    });
  };

  const pause = () => {
    if (!pauseUntilDay) return;
    writePreferences.mutate(
      {
        pause_from: pauseFromDay ? dayStart(pauseFromDay) : null,
        pause_until: dayEnd(pauseUntilDay),
      },
      {
        onSuccess: () => {
          setPauseFromDay("");
          setPauseUntilDay("");
        },
        onError: () => toast.error(t("notifications.timing.saveError")),
      }
    );
  };

  const resume = () =>
    writePreferences.mutate(
      { clear_pause: true },
      {
        onSuccess: () => toast.success(t("notifications.timing.pause.resumed")),
        onError: () => toast.error(t("notifications.timing.saveError")),
      }
    );

  // The registry decides which rows exist and which switches move. A row with
  // no switch at all is not a preference, so it is not shown.
  const grouped = useMemo(() => {
    const rows = (preferences?.categories ?? []).filter((row) => row.mutable_channels.length > 0);
    return GROUP_ORDER.map((group) => ({
      group,
      rows: rows.filter((row) => row.group === group),
    })).filter((section) => section.rows.length > 0);
  }, [preferences?.categories]);

  const visibleChannels = CHANNELS.filter((channel) => channel !== "push" || showPushColumn);

  const digestRows = (preferences?.categories ?? []).filter(
    (row) => row.group === CategoryGroup.digests
  );

  // The rows each community can switch off on its own.
  const communityRows = grouped.flatMap((section) =>
    section.rows.filter((row) => row.per_community)
  );

  // What a closed community says about itself: which of its rows it has
  // switched off, so there is a reason to open it.
  const communitySummary = (community: CommunityNotificationSettings) => {
    if (community.muted) return t("notifications.communities.mutedSummary");
    const off = communityRows
      .filter((row) => community.off.includes(row.category))
      .map((row) => t(`notifications.categories.${row.category}`));
    if (off.length === 0) return t("notifications.communities.followsAbove");
    return t("notifications.communities.offHere", {
      rows: listFormat(i18n.resolvedLanguage ?? i18n.language, { type: "conjunction" }).format(off),
    });
  };

  const isOn = (row: NotificationCategoryRead, channel: Channel) => {
    const stored = preferences?.settings?.[row.category]?.[channel];
    if (typeof stored === "boolean") return stored;
    return row.defaults[channel] ?? true;
  };

  const writeSwitch = (payload: NotificationPreferencesUpdate) =>
    writePreferences.mutate(payload, {
      onError: () => toast.error(t("notifications.toggleError")),
    });

  const saveQuietHours = (enabled: boolean) => {
    const sent = quietHours.values;
    writePreferences.mutate(enabled ? { quiet_hours: sent } : { clear_quiet_hours: true }, {
      onSuccess: () => quietHours.settle(sent),
      onError: () => {
        quietHours.reset(sent);
        toast.error(t("notifications.toggleError"));
      },
    });
  };

  const reminderLabel = (minutes: number): string => {
    if (minutes === 0) return t("notifications.reminderLeadTime.atStart");
    if (minutes >= 1440) return t("notifications.reminderLeadTime.day", { count: minutes / 1440 });
    if (minutes >= 60) return t("notifications.reminderLeadTime.hour", { count: minutes / 60 });
    return t("notifications.reminderLeadTime.minute", { count: minutes });
  };

  const handleReminderMinutesChange = (raw: string) => {
    const next = Number(raw);
    setPendingReminder(next);
    updateSchedule.mutate(
      { event_reminder_minutes_before: next },
      {
        onSuccess: async () => {
          await refreshUser();
          setPendingReminder(null);
        },
        onError: () => {
          setPendingReminder(null);
          toast.error(t("notifications.toggleError"));
        },
      }
    );
  };

  // Wide, the channels are columns under a header. Narrow, a row's text takes
  // the full width and its switches sit beneath it in one even strip, each
  // named, because a column of switches beside the text would squeeze the text
  // into a sliver.
  const gridColumns = { gridTemplateColumns: `1fr repeat(${visibleChannels.length}, auto)` };
  const stripColumns = {
    gridTemplateColumns: `repeat(${visibleChannels.length}, minmax(0, 1fr))`,
  };

  const renderGrid = () => (
    <div className="space-y-1">
      <div className="canvas-sm:grid hidden items-center gap-4 border-b pb-2" style={gridColumns}>
        <p className="font-medium text-muted-foreground text-sm">
          {t("notifications.categoryHeader")}
        </p>
        {visibleChannels.map((channel) => (
          <p key={channel} className="w-16 text-center font-medium text-muted-foreground text-sm">
            {t(`notifications.channels.${channel}`)}
          </p>
        ))}
      </div>

      {grouped.map((section) => (
        <div key={section.group}>
          <p className="pt-4 pb-1 font-medium text-muted-foreground text-xs uppercase tracking-wide">
            {t(`notifications.groups.${section.group}`)}
          </p>
          {section.rows.map((row) => (
            <div key={row.category} className="border-b last:border-b-0">
              <div
                className="flex canvas-sm:grid flex-col canvas-sm:items-center canvas-sm:gap-4 gap-3 py-3"
                style={gridColumns}
              >
                <div>
                  <p className="font-medium">{t(`notifications.categories.${row.category}`)}</p>
                  <p className="text-muted-foreground text-sm">
                    {t(`notifications.categoryDescriptions.${row.category}`)}
                  </p>
                </div>
                <div
                  className="grid canvas-sm:contents rounded-md bg-muted/40"
                  style={stripColumns}
                >
                  {visibleChannels.map((channel) => {
                    const mutable = row.mutable_channels.includes(channel);
                    const Icon = CHANNEL_ICONS[channel];
                    return (
                      <div
                        key={channel}
                        className="flex canvas-sm:w-16 flex-col items-center gap-2 canvas-sm:py-0 py-2.5"
                      >
                        <span
                          className="flex canvas-sm:hidden items-center gap-1.5 text-muted-foreground text-xs"
                          aria-hidden
                        >
                          <Icon className="size-3.5" />
                          {t(`notifications.channels.${channel}`)}
                        </span>
                        <Switch
                          checked={mutable ? isOn(row, channel) : true}
                          disabled={!mutable || writePreferences.isPending}
                          aria-label={t("notifications.switchLabel", {
                            category: t(`notifications.categories.${row.category}`),
                            channel: t(`notifications.channels.${channel}`),
                          })}
                          onCheckedChange={(enabled) =>
                            writeSwitch({
                              channels: [{ category: row.category, channel, enabled }],
                            })
                          }
                        />
                      </div>
                    );
                  })}
                </div>
              </div>
              {row.category === "assignments" && (
                <div className="flex items-center gap-2 pb-3">
                  <Label htmlFor="reminder-lead-time" className="text-muted-foreground text-sm">
                    {t("notifications.reminderLeadTime.label")}
                  </Label>
                  <Select
                    value={String(reminderMinutes)}
                    onValueChange={handleReminderMinutesChange}
                  >
                    <SelectTrigger id="reminder-lead-time" className="w-44">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {REMINDER_MINUTE_OPTIONS.map((minutes) => (
                        <SelectItem key={minutes} value={String(minutes)}>
                          {reminderLabel(minutes)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );

  return (
    <div className="space-y-6">
      {isSupported && (
        <SettingsSection
          title={t("notifications.pushNotifications")}
          description={
            permissionStatus === "denied"
              ? t("notifications.pushBlockedDescription")
              : t("notifications.pushDescription")
          }
          action={
            permissionStatus === "prompt" ? (
              <Button onClick={requestPermission} size="sm">
                {t("notifications.enablePush")}
              </Button>
            ) : permissionStatus === "granted" ? (
              <Badge variant="secondary">{t("notifications.pushEnabled")}</Badge>
            ) : permissionStatus === "denied" ? (
              <Badge variant="destructive">{t("notifications.pushBlocked")}</Badge>
            ) : null
          }
        />
      )}

      <SettingsSection
        title={t("notifications.channelsTitle")}
        description={t("notifications.channelsDescription")}
      >
        {isLoading ? (
          <p className="text-muted-foreground text-sm">{t("common:loading")}</p>
        ) : (
          renderGrid()
        )}
      </SettingsSection>

      <SettingsSection
        title={t("notifications.digests.title")}
        description={t("notifications.digests.description")}
      >
        {digestRows.map((row) => {
          const digest = preferences?.digests?.[row.category];
          const name = t(`notifications.categories.${row.category}`);
          return (
            <div key={row.category} className="space-y-3 border-b pb-4">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="font-medium">{name}</p>
                  <p className="text-muted-foreground text-sm">
                    {t(`notifications.categoryDescriptions.${row.category}`)}
                  </p>
                </div>
                <div className="flex gap-4">
                  {visibleChannels
                    .filter((channel) => row.mutable_channels.includes(channel))
                    .map((channel) => {
                      const Icon = CHANNEL_ICONS[channel];
                      return (
                        <div key={channel} className="flex flex-col items-center gap-2">
                          <span
                            className="flex items-center gap-1.5 text-muted-foreground text-xs"
                            aria-hidden
                          >
                            <Icon className="size-3.5" />
                            {t(`notifications.channels.${channel}`)}
                          </span>
                          <Switch
                            checked={isOn(row, channel)}
                            disabled={writePreferences.isPending}
                            aria-label={t("notifications.switchLabel", {
                              category: name,
                              channel: t(`notifications.channels.${channel}`),
                            })}
                            onCheckedChange={(enabled) =>
                              writeSwitch({
                                channels: [{ category: row.category, channel, enabled }],
                              })
                            }
                          />
                        </div>
                      );
                    })}
                </div>
              </div>
              <div className="grid grid-cols-fill-48/3 gap-4">
                <div className="space-y-2">
                  <Label htmlFor={`${row.category}-cadence`}>
                    {t("notifications.digests.frequency")}
                  </Label>
                  <Select
                    disabled={writePreferences.isPending}
                    value={digest?.cadence ?? "daily"}
                    onValueChange={(value) =>
                      writeDigest(row.category, { cadence: value as DigestCadence })
                    }
                  >
                    <SelectTrigger id={`${row.category}-cadence`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {DIGEST_CADENCES.map((cadence) => (
                        <SelectItem key={cadence} value={cadence}>
                          {t(`notifications.digests.${cadence}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {digest?.cadence === "weekly" && (
                  <div className="space-y-2">
                    <Label htmlFor={`${row.category}-weekday`}>
                      {t("notifications.timing.day")}
                    </Label>
                    <Select
                      disabled={writePreferences.isPending}
                      value={String(digest.weekday)}
                      onValueChange={(value) =>
                        writeDigest(row.category, { weekday: Number(value) })
                      }
                    >
                      <SelectTrigger id={`${row.category}-weekday`}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {WEEKDAYS.map((day) => (
                          <SelectItem key={day} value={String(day)}>
                            {t(`notifications.weekdays.${day}`)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
                <div className="space-y-2">
                  <Label htmlFor={`${row.category}-time`}>{t("notifications.timing.time")}</Label>
                  <Input
                    key={digest?.at}
                    id={`${row.category}-time`}
                    type="time"
                    disabled={writePreferences.isPending}
                    defaultValue={digest?.at}
                    onBlur={(event) => {
                      if (event.target.value && event.target.value !== digest?.at) {
                        writeDigest(row.category, { at: event.target.value });
                      }
                    }}
                  />
                </div>
              </div>
            </div>
          );
        })}

        <div className="space-y-3">
          <div>
            <p className="font-medium">{t("notifications.digests.gatheredEmail")}</p>
            <p className="text-muted-foreground text-sm">
              {t("notifications.digests.gatheredEmailHelp")}
            </p>
          </div>
          <div className="grid grid-cols-fill-48/3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="email-cadence">{t("notifications.timing.cadence.label")}</Label>
              <Select
                disabled={writePreferences.isPending}
                value={schedule?.cadence ?? "instant"}
                onValueChange={(value) => writeEmail({ cadence: value as EmailCadence })}
              >
                <SelectTrigger id="email-cadence">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CADENCES.map((cadence) => (
                    <SelectItem key={cadence} value={cadence}>
                      {t(`notifications.timing.cadence.${cadence}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {schedule?.cadence === "weekly" && (
              <div className="space-y-2">
                <Label htmlFor="email-weekday">{t("notifications.timing.day")}</Label>
                <Select
                  disabled={writePreferences.isPending}
                  value={String(schedule.weekday)}
                  onValueChange={(value) => writeEmail({ weekday: Number(value) })}
                >
                  <SelectTrigger id="email-weekday">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {WEEKDAYS.map((day) => (
                      <SelectItem key={day} value={String(day)}>
                        {t(`notifications.weekdays.${day}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            {(schedule?.cadence === "daily" || schedule?.cadence === "weekly") && (
              <div className="space-y-2">
                <Label htmlFor="email-time">{t("notifications.timing.time")}</Label>
                <Input
                  key={schedule.at}
                  id="email-time"
                  type="time"
                  disabled={writePreferences.isPending}
                  defaultValue={schedule.at}
                  onBlur={(event) => {
                    if (event.target.value && event.target.value !== schedule.at) {
                      writeEmail({ at: event.target.value });
                    }
                  }}
                />
              </div>
            )}
          </div>
          {schedule && schedule.cadence !== "instant" && (
            <SettingsRow
              label={t("notifications.timing.personalInstant")}
              description={t("notifications.timing.personalInstantHelp")}
            >
              <Switch
                checked={schedule.personal_instant}
                aria-label={t("notifications.timing.personalInstant")}
                onCheckedChange={(personal_instant) => writeEmail({ personal_instant })}
              />
            </SettingsRow>
          )}
        </div>

        <p className="text-muted-foreground text-xs">
          {t("notifications.digests.afterPause")}{" "}
          {t("notifications.timing.zone", { timezone: user.timezone ?? "UTC" })}{" "}
          <Link to="/profile/interface" className="underline underline-offset-2">
            {t("notifications.timing.changeZone")}
          </Link>
        </p>
      </SettingsSection>

      <SettingsSection title={t("notifications.quietTitle")}>
        <SettingsRow
          label={t("notifications.timing.respectPresence")}
          description={t("notifications.timing.respectPresenceHelp")}
        >
          <Switch
            checked={preferences?.respect_presence ?? true}
            aria-label={t("notifications.timing.respectPresence")}
            onCheckedChange={(checked) => writeTiming({ respect_presence: checked })}
          />
        </SettingsRow>

        <SettingsRow
          label={t("notifications.quietHours.title")}
          description={t("notifications.quietHours.description")}
          below={
            preferences?.quiet_hours ? (
              <div className="grid grid-cols-pair gap-4 sm:max-w-md">
                <div className="space-y-2">
                  <Label htmlFor="quiet-start">{t("notifications.quietHours.from")}</Label>
                  <Input
                    id="quiet-start"
                    type="time"
                    value={quietHours.values.start}
                    onChange={(event) => quietHours.set({ start: event.target.value })}
                    onBlur={() => saveQuietHours(true)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="quiet-end">{t("notifications.quietHours.to")}</Label>
                  <Input
                    id="quiet-end"
                    type="time"
                    value={quietHours.values.end}
                    onChange={(event) => quietHours.set({ end: event.target.value })}
                    onBlur={() => saveQuietHours(true)}
                  />
                </div>
              </div>
            ) : null
          }
        >
          <Switch
            checked={Boolean(preferences?.quiet_hours)}
            aria-label={t("notifications.quietHours.title")}
            onCheckedChange={saveQuietHours}
          />
        </SettingsRow>

        {booked ? (
          <SettingsRow
            label={
              running
                ? t("notifications.timing.pause.active", { until: formatDate(booked.until) })
                : t("notifications.timing.pause.scheduled", {
                    from: formatDate(booked.since),
                    until: formatDate(booked.until),
                  })
            }
            description={t("notifications.timing.pause.note")}
          >
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={writePreferences.isPending}
              onClick={resume}
            >
              {running
                ? t("notifications.timing.pause.resume")
                : t("notifications.timing.pause.cancel")}
            </Button>
          </SettingsRow>
        ) : (
          <SettingsRow
            label={t("notifications.timing.pause.title")}
            description={t("notifications.timing.pause.description")}
            below={
              <div className="space-y-2">
                <div className="flex flex-wrap items-end gap-3">
                  <div className="space-y-1">
                    <Label htmlFor="pause-from">{t("notifications.timing.pause.from")}</Label>
                    <DateTimePicker
                      id="pause-from"
                      value={pauseFromDay}
                      onChange={setPauseFromDay}
                      disabled={writePreferences.isPending}
                      placeholder={t("notifications.timing.pause.fromPlaceholder")}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="pause-until">{t("notifications.timing.pause.until")}</Label>
                    <DateTimePicker
                      id="pause-until"
                      value={pauseUntilDay}
                      onChange={setPauseUntilDay}
                      disabled={writePreferences.isPending}
                      placeholder={t("notifications.timing.pause.untilPlaceholder")}
                    />
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={!pauseUntilDay || writePreferences.isPending}
                    onClick={pause}
                  >
                    {t("notifications.timing.pause.confirm")}
                  </Button>
                </div>
                <p className="text-muted-foreground text-xs">
                  {t("notifications.timing.pause.help")}
                </p>
              </div>
            }
          />
        )}
      </SettingsSection>

      {(preferences?.communities?.length ?? 0) > 0 && (
        <SettingsSection
          title={t("notifications.communities.title")}
          description={t("notifications.communities.description")}
        >
          <div className="space-y-3">
            {preferences?.communities?.map((community) => (
              <details key={community.community_id} className="group rounded-md border">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 rounded-md p-3 hover:bg-muted/50 [&::-webkit-details-marker]:hidden">
                  <span className="flex min-w-0 items-center gap-2">
                    <ChevronRight
                      className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90"
                      aria-hidden
                    />
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{community.community_name}</span>
                      <span className="block text-muted-foreground text-xs">
                        {communitySummary(community)}
                      </span>
                    </span>
                  </span>
                  <span className="flex items-center gap-2 text-muted-foreground text-sm">
                    <span aria-hidden>{t("notifications.communities.mute")}</span>
                    <Switch
                      checked={community.muted}
                      disabled={writePreferences.isPending}
                      aria-label={t("notifications.communities.muteLabel", {
                        community: community.community_name,
                      })}
                      onCheckedChange={(muted) =>
                        writeSwitch({ mutes: [{ community_id: community.community_id, muted }] })
                      }
                    />
                  </span>
                </summary>
                <div className="border-t p-3">
                  {community.muted ? (
                    <p className="text-muted-foreground text-sm">
                      {t("notifications.communities.mutedHelp")}
                    </p>
                  ) : (
                    <div className="space-y-4">
                      {communityRows.map((row) => {
                        const label = t(`notifications.categories.${row.category}`);
                        return (
                          <SettingsRow key={row.category} label={label}>
                            <Switch
                              checked={!community.off.includes(row.category)}
                              disabled={writePreferences.isPending}
                              aria-label={t("notifications.communities.rowLabel", {
                                row: label,
                                community: community.community_name,
                              })}
                              onCheckedChange={(enabled) =>
                                writeSwitch({
                                  rows: [
                                    {
                                      community_id: community.community_id,
                                      category: row.category,
                                      enabled,
                                    },
                                  ],
                                })
                              }
                            />
                          </SettingsRow>
                        );
                      })}
                    </div>
                  )}
                </div>
              </details>
            ))}
          </div>
        </SettingsSection>
      )}
    </div>
  );
};
