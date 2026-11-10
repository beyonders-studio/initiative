import { Capacitor } from "@capacitor/core";
import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { useEventTheme } from "@/hooks/useEventTheme";
import { useKeepScreenAwake } from "@/hooks/useKeepScreenAwake";
import { type Theme, useTheme } from "@/hooks/useTheme";
import { useUpdateCurrentUser } from "@/hooks/useUsers";
import { autoUpdateConsented, desktopCanUpdate, setAutoUpdateConsent } from "@/lib/desktopUpdates";
import { toast } from "@/lib/mascotToast";
import {
  dispatchTaskCompletionVisualFeedback,
  parseTaskCompletionVisualFeedback,
  playTaskCompletionSound,
  TASK_COMPLETION_VISUAL_FEEDBACK_VALUES,
  type TaskCompletionVisualFeedback,
  triggerTaskCompletionHaptic,
} from "@/lib/taskCompletionFeedback";
import { TIMEZONE_OPTIONS } from "@/lib/timezones";
import { ThemePicker } from "@/pages/my/settings/ThemePicker";
import Desktop from "@/plugins/desktop";
import { Button } from "@/ui/button";
import { Combobox } from "@/ui/combobox";
import { parseTimeFormat, TIME_FORMAT_PREFERENCES } from "@/ui/host";
import { Input } from "@/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Switch } from "@/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

const WEEK_START_OPTIONS = [
  { labelKey: "dates:weekdays.sunday", value: 0 },
  { labelKey: "dates:weekdays.monday", value: 1 },
  { labelKey: "dates:weekdays.tuesday", value: 2 },
  { labelKey: "dates:weekdays.wednesday", value: 3 },
  { labelKey: "dates:weekdays.thursday", value: 4 },
  { labelKey: "dates:weekdays.friday", value: 5 },
  { labelKey: "dates:weekdays.saturday", value: 6 },
];

const THEME_CHOICES = [
  { value: "system", icon: Monitor, labelKey: "nav:themeSystem" },
  { value: "light", icon: Sun, labelKey: "nav:themeLight" },
  { value: "dark", icon: Moon, labelKey: "nav:themeDark" },
] as const;

const RECENT_TABS_LIMIT_MIN = 1;
const RECENT_TABS_LIMIT_MAX = 100;
const RECENT_TABS_LIMIT_DEFAULT = 20;

const clampRecentTabsLimit = (value: number): number =>
  Math.min(
    RECENT_TABS_LIMIT_MAX,
    Math.max(RECENT_TABS_LIMIT_MIN, Math.round(value || RECENT_TABS_LIMIT_DEFAULT))
  );

const LANGUAGE_OPTIONS = [
  { label: "English", value: "en" },
  { label: "Español", value: "es" },
  { label: "Français", value: "fr" },
  { label: "Deutsch", value: "de" },
];

/** The account's interface preferences, as the page shows them. */
const prefsOf = (user: UserRead) => ({
  week_starts_on: user.week_starts_on ?? 0,
  time_format: parseTimeFormat(user.time_format),
  recent_tabs_limit: user.recent_tabs_limit ?? RECENT_TABS_LIMIT_DEFAULT,
  color_theme: user.color_theme ?? "kobold",
  locale: user.locale ?? "en",
  timezone: user.timezone ?? "UTC",
  task_completion_visual_feedback: parseTaskCompletionVisualFeedback(
    user.task_completion_visual_feedback
  ),
  task_completion_audio_feedback: user.task_completion_audio_feedback ?? true,
  task_completion_haptic_feedback: user.task_completion_haptic_feedback ?? true,
  smart_task_titles: user.smart_task_titles ?? true,
});
type InterfacePrefs = ReturnType<typeof prefsOf>;

interface UserSettingsInterfacePageProps {
  user: UserRead;
  acceptUser: (user: UserRead) => void;
}

export const InterfacePage = ({ user, acceptUser }: UserSettingsInterfacePageProps) => {
  const { t, i18n } = useTranslation(["settings", "dates", "nav"]);
  // What the server says, with each choice shown from the moment it is made
  // until its save settles.
  const [pendingPrefs, setPendingPrefs] = useState<Partial<InterfacePrefs>>({});
  const saved = prefsOf(user);
  const prefs: InterfacePrefs = { ...saved, ...pendingPrefs };
  const showPrefs = (patch: Partial<InterfacePrefs>) =>
    setPendingPrefs((previous) => ({ ...previous, ...patch }));
  // A choice stops being shown once the save that sent it settles; a newer
  // choice of the same field waits for its own.
  const dropPrefs = (sent: { [K in keyof InterfacePrefs]?: unknown }) =>
    setPendingPrefs(
      (previous) =>
        Object.fromEntries(
          Object.entries(previous).filter(
            ([key, value]) => !(key in sent && Object.is(sent[key as keyof InterfacePrefs], value))
          )
        ) as Partial<InterfacePrefs>
    );
  const {
    enabled: keepAwake,
    setEnabled: setKeepAwake,
    supported: keepAwakeSupported,
  } = useKeepScreenAwake();
  const { theme, setTheme } = useTheme();
  const { allowed: eventThemes, setAllowed: setEventThemes } = useEventTheme();
  const [canAutoUpdate, setCanAutoUpdate] = useState(false);
  const [autoUpdate, setAutoUpdate] = useState(autoUpdateConsented);

  // The desktop app's own settings, kept on this computer; null elsewhere.
  const [desktopShell, setDesktopShell] = useState<Awaited<
    ReturnType<typeof Desktop.getSettings>
  > | null>(null);

  // A write the computer refused shows what is actually set, not what was asked.
  const saveDesktopShell = (write: Promise<void>) => {
    void write.catch(() => {
      toast.error(t("interface.updateError"));
      void Desktop.getSettings()
        .then(setDesktopShell)
        .catch(() => {});
    });
  };

  useEffect(() => {
    void desktopCanUpdate().then(setCanAutoUpdate);
    if (Capacitor.getPlatform() === "electron") {
      void Desktop.getSettings()
        .then(setDesktopShell)
        .catch(() => {});
    }
  }, []);

  const updateInterfacePrefs = useUpdateCurrentUser({
    onSuccess: (saved, variables) => {
      if (variables.recent_tabs_limit !== undefined) {
        // The header tabs bar caches recents for 30s; refetch so a higher
        // limit surfaces more items immediately.
        void invalidate(q.personalItems());
      }
      if (variables.locale) {
        void i18n.changeLanguage(variables.locale);
      }
      toast.success(t("interface.updateSuccess"));
      // The fields this save sent read from its answer; everything else on the
      // account stays as the last full read had it.
      acceptUser({
        ...user,
        ...Object.fromEntries(
          Object.keys(variables).map((key) => [key, saved[key as keyof UserRead]])
        ),
      });
      dropPrefs(variables);
    },
    onError: (_error, variables) => {
      dropPrefs(variables);
      toast.error(t("interface.updateError"));
    },
  });

  const savePrefs = (patch: Partial<InterfacePrefs>) => {
    showPrefs(patch);
    updateInterfacePrefs.mutate(patch);
  };

  const commitRecentTabsLimit = () => {
    const clamped = clampRecentTabsLimit(prefs.recent_tabs_limit);
    if (clamped === saved.recent_tabs_limit) {
      dropPrefs({ recent_tabs_limit: prefs.recent_tabs_limit });
    } else {
      savePrefs({ recent_tabs_limit: clamped });
    }
  };

  const pending = updateInterfacePrefs.isPending;

  return (
    <div className="space-y-6">
      <SettingsSection title={t("interface.appearanceTitle")}>
        <ThemePicker
          value={prefs.color_theme}
          disabled={pending}
          onChange={(next) => savePrefs({ color_theme: next })}
        />
        <SettingsRow
          label={t("interface.recentTabsLimit")}
          description={t("interface.recentTabsLimitDescription")}
        >
          <Input
            type="number"
            min={RECENT_TABS_LIMIT_MIN}
            max={RECENT_TABS_LIMIT_MAX}
            value={prefs.recent_tabs_limit}
            onChange={(event) => showPrefs({ recent_tabs_limit: Number(event.target.value) })}
            onBlur={commitRecentTabsLimit}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.currentTarget.blur();
              }
            }}
            disabled={pending}
            className="sm:w-24"
          />
        </SettingsRow>
      </SettingsSection>

      <SettingsSection title={t("interface.regionTitle")}>
        <SettingsRow
          label={t("interface.language")}
          description={t("interface.languageDescription")}
        >
          <Select
            value={prefs.locale}
            onValueChange={(next) => savePrefs({ locale: next })}
            disabled={pending}
          >
            <SelectTrigger className="sm:w-52">
              <SelectValue>
                {LANGUAGE_OPTIONS.find((l) => l.value === prefs.locale)?.label ?? "English"}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {LANGUAGE_OPTIONS.map((lang) => (
                <SelectItem key={lang.value} value={lang.value}>
                  {lang.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </SettingsRow>

        <SettingsRow label={t("profile.timezoneLabel")} description={t("profile.timezoneHelp")}>
          <div className="w-full sm:w-52">
            <Combobox
              items={TIMEZONE_OPTIONS.map((tz) => ({ value: tz, label: tz }))}
              value={prefs.timezone}
              onValueChange={(next) => savePrefs({ timezone: next })}
              placeholder={t("profile.timezonePlaceholder")}
              emptyMessage={t("profile.timezoneEmpty")}
            />
          </div>
        </SettingsRow>

        <SettingsRow
          label={t("interface.weekStartsOn")}
          description={t("interface.weekStartsOnDescription")}
        >
          <Select
            value={String(prefs.week_starts_on)}
            onValueChange={(next) => savePrefs({ week_starts_on: Number(next) })}
            disabled={pending}
          >
            <SelectTrigger className="sm:w-52">
              <SelectValue>
                {t(
                  (WEEK_START_OPTIONS.find((option) => option.value === prefs.week_starts_on)
                    ?.labelKey ?? "dates:weekdays.sunday") as never
                )}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {WEEK_START_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={String(option.value)}>
                  {t(option.labelKey as never)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </SettingsRow>

        <SettingsRow
          label={t("interface.timeFormat.label")}
          description={t("interface.timeFormat.description")}
        >
          <Select
            value={prefs.time_format}
            onValueChange={(next) => savePrefs({ time_format: parseTimeFormat(next) })}
            disabled={pending}
          >
            <SelectTrigger className="sm:w-52">
              <SelectValue>
                {t(`interface.timeFormat.options.${prefs.time_format}` as never)}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {TIME_FORMAT_PREFERENCES.map((value) => (
                <SelectItem key={value} value={value}>
                  {t(`interface.timeFormat.options.${value}` as never)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection
        title={t("interface.addingTitle")}
        description={t("interface.addingDescription")}
      >
        <SettingsRow
          label={t("interface.smartTaskTitles.label")}
          description={t("interface.smartTaskTitles.description")}
        >
          <Switch
            checked={prefs.smart_task_titles}
            onCheckedChange={(next) => savePrefs({ smart_task_titles: next })}
            disabled={pending}
          />
        </SettingsRow>
      </SettingsSection>

      <SettingsSection
        title={t("interface.completionTitle")}
        description={t("interface.completionDescription")}
      >
        <SettingsRow
          label={t("interface.taskCompletionVisualFeedback.label")}
          description={t("interface.taskCompletionVisualFeedback.description")}
        >
          <Select
            value={prefs.task_completion_visual_feedback}
            onValueChange={(next) =>
              savePrefs({ task_completion_visual_feedback: next as TaskCompletionVisualFeedback })
            }
            disabled={pending}
          >
            <SelectTrigger className="sm:w-52">
              <SelectValue>
                {t(
                  `interface.taskCompletionVisualFeedback.options.${prefs.task_completion_visual_feedback}` as never
                )}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {TASK_COMPLETION_VISUAL_FEEDBACK_VALUES.map((value) => (
                <SelectItem key={value} value={value}>
                  {t(`interface.taskCompletionVisualFeedback.options.${value}` as never)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              dispatchTaskCompletionVisualFeedback(prefs.task_completion_visual_feedback)
            }
            disabled={prefs.task_completion_visual_feedback === "none"}
          >
            {t("interface.taskCompletionVisualFeedback.preview")}
          </Button>
        </SettingsRow>

        <SettingsRow
          label={t("interface.taskCompletionAudioFeedback.label")}
          description={t("interface.taskCompletionAudioFeedback.description")}
          action={
            <>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => playTaskCompletionSound()}
              >
                {t("interface.taskCompletionAudioFeedback.preview")}
              </Button>
              <Switch
                checked={prefs.task_completion_audio_feedback}
                onCheckedChange={(next) => savePrefs({ task_completion_audio_feedback: next })}
                disabled={pending}
              />
            </>
          }
        />

        <SettingsRow
          label={t("interface.taskCompletionHapticFeedback.label")}
          description={t("interface.taskCompletionHapticFeedback.description")}
          action={
            <>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => triggerTaskCompletionHaptic()}
              >
                {t("interface.taskCompletionHapticFeedback.preview")}
              </Button>
              <Switch
                checked={prefs.task_completion_haptic_feedback}
                onCheckedChange={(next) => savePrefs({ task_completion_haptic_feedback: next })}
                disabled={pending}
              />
            </>
          }
        />
      </SettingsSection>

      {/* Kept by this browser or this computer rather than the account. */}
      <SettingsSection
        title={t("interface.deviceTitle")}
        description={t("interface.deviceDescription")}
      >
        <SettingsRow
          label={t("interface.mode")}
          action={
            <TooltipProvider delayDuration={300}>
              <ToggleGroup
                type="single"
                variant="outline"
                value={theme}
                onValueChange={(next) => next && setTheme(next as Theme)}
                aria-label={t("interface.mode")}
              >
                {THEME_CHOICES.map(({ value, icon: Icon, labelKey }) => (
                  <Tooltip key={value}>
                    <TooltipTrigger asChild>
                      <ToggleGroupItem value={value} aria-label={t(labelKey)}>
                        <Icon />
                      </ToggleGroupItem>
                    </TooltipTrigger>
                    <TooltipContent>{t(labelKey)}</TooltipContent>
                  </Tooltip>
                ))}
              </ToggleGroup>
            </TooltipProvider>
          }
        />
        <SettingsRow
          label={t("interface.eventThemes.label")}
          description={t("interface.eventThemes.description")}
        >
          <Switch checked={eventThemes} onCheckedChange={setEventThemes} />
        </SettingsRow>
        <SettingsRow
          label={t("interface.keepScreenAwake.label")}
          description={
            keepAwakeSupported
              ? t("interface.keepScreenAwake.description")
              : t("interface.keepScreenAwake.unsupported")
          }
        >
          <Switch
            checked={keepAwake}
            onCheckedChange={setKeepAwake}
            disabled={!keepAwakeSupported}
          />
        </SettingsRow>

        {canAutoUpdate ? (
          <SettingsRow
            label={t("interface.desktopAutoUpdate.label")}
            description={t("interface.desktopAutoUpdate.description")}
          >
            <Switch
              checked={autoUpdate}
              onCheckedChange={(next) => {
                setAutoUpdate(next);
                setAutoUpdateConsent(next);
              }}
            />
          </SettingsRow>
        ) : null}

        {desktopShell?.tray ? (
          <SettingsRow
            label={t("interface.desktopKeepRunning.label")}
            description={t("interface.desktopKeepRunning.description")}
          >
            <Switch
              checked={desktopShell.keepRunning}
              onCheckedChange={(enabled) => {
                setDesktopShell({ ...desktopShell, keepRunning: enabled });
                saveDesktopShell(Desktop.setKeepRunning({ enabled }));
              }}
            />
          </SettingsRow>
        ) : null}

        {desktopShell ? (
          <SettingsRow
            label={t("interface.desktopOpenAtLogin.label")}
            description={t("interface.desktopOpenAtLogin.description")}
          >
            <Switch
              checked={desktopShell.openAtLogin}
              onCheckedChange={(enabled) => {
                setDesktopShell({ ...desktopShell, openAtLogin: enabled });
                saveDesktopShell(Desktop.setOpenAtLogin({ enabled }));
              }}
            />
          </SettingsRow>
        ) : null}
      </SettingsSection>
    </div>
  );
};
