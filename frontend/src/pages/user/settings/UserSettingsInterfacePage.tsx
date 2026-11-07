import { Capacitor } from "@capacitor/core";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useKeepScreenAwake } from "@/hooks/useKeepScreenAwake";
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
import type { ThemeColors } from "@/lib/themes";
import { getThemeList } from "@/lib/themes";
import { TIMEZONE_OPTIONS } from "@/lib/timezones";
import { cn } from "@/lib/utils";
import Desktop from "@/plugins/desktop";
import { parseTimeFormat, TIME_FORMAT_PREFERENCES } from "@/ui/host";

const WEEK_START_OPTIONS = [
  { labelKey: "dates:weekdays.sunday", value: 0 },
  { labelKey: "dates:weekdays.monday", value: 1 },
  { labelKey: "dates:weekdays.tuesday", value: 2 },
  { labelKey: "dates:weekdays.wednesday", value: 3 },
  { labelKey: "dates:weekdays.thursday", value: 4 },
  { labelKey: "dates:weekdays.friday", value: 5 },
  { labelKey: "dates:weekdays.saturday", value: 6 },
];

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

function MiniMockup({ colors }: { colors: ThemeColors }) {
  const c = (value: string): string => `oklch(${value})`;

  return (
    <div
      className="flex overflow-hidden rounded-lg border"
      style={{
        height: 88,
        borderColor: c(colors.border),
        backgroundColor: c(colors.background),
      }}
    >
      {/* Sidebar strip */}
      <div
        className="flex flex-col gap-1.5 p-1.5"
        style={{ width: 28, backgroundColor: c(colors.sidebar) }}
      >
        <div
          className="rounded"
          style={{ height: 6, width: "100%", backgroundColor: c(colors.sidebarPrimary) }}
        />
        <div
          className="rounded"
          style={{ height: 6, width: "100%", backgroundColor: c(colors.muted) }}
        />
        <div
          className="rounded"
          style={{ height: 6, width: "100%", backgroundColor: c(colors.muted) }}
        />
      </div>

      {/* Main area */}
      <div className="flex flex-1 flex-col gap-2 p-2">
        {/* Mini card */}
        <div
          className="flex flex-col gap-1.5 rounded p-2"
          style={{ backgroundColor: c(colors.card) }}
        >
          <div
            className="rounded"
            style={{
              height: 6,
              width: "80%",
              backgroundColor: c(colors.foreground),
              opacity: 0.8,
            }}
          />
          <div
            className="rounded"
            style={{
              height: 4,
              width: "50%",
              backgroundColor: c(colors.mutedForeground),
              opacity: 0.6,
            }}
          />
          <div className="mt-1 flex gap-1">
            <div
              className="rounded"
              style={{ height: 8, width: 24, backgroundColor: c(colors.ring) }}
            />
            <div
              className="rounded"
              style={{ height: 8, width: 24, backgroundColor: c(colors.border) }}
            />
          </div>
        </div>

        {/* Chart color swatches */}
        <div className="flex gap-0.5">
          {[colors.chart1, colors.chart2, colors.chart3, colors.chart4, colors.chart5].map(
            (color) => (
              <div
                key={color}
                className="flex-1 rounded-sm"
                style={{ height: 6, backgroundColor: c(color) }}
              />
            )
          )}
        </div>
      </div>
    </div>
  );
}

/** Every theme as a tile showing it in light and dark; the chosen one is ringed. */
function ThemePicker({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (themeId: string) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation("settings");
  return (
    <div
      role="radiogroup"
      aria-label={t("interface.colorTheme")}
      className="grid grid-cols-fill-56/3 gap-3"
    >
      {getThemeList().map((theme) => {
        const selected = theme.id === value;
        return (
          // biome-ignore lint/a11y/useSemanticElements: a tile of previews, not a bare radio input
          <button
            key={theme.id}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => onChange(theme.id)}
            className={cn(
              "space-y-2 rounded-lg border p-2 text-left transition-colors hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60",
              selected && "border-primary ring-2 ring-primary"
            )}
          >
            <div className="grid grid-cols-2 gap-1.5">
              <MiniMockup colors={theme.light} />
              <MiniMockup colors={theme.dark} />
            </div>
            <div className="px-1 pb-1">
              <p className="font-medium text-sm">{theme.name}</p>
              <p className="text-muted-foreground text-xs">
                {t(`interface.themeDescriptions.${theme.id}` as never)}
              </p>
            </div>
          </button>
        );
      })}
    </div>
  );
}

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

export const UserSettingsInterfacePage = ({ user, acceptUser }: UserSettingsInterfacePageProps) => {
  const { t, i18n } = useTranslation(["settings", "dates"]);
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
          htmlFor="recent-tabs-limit"
        >
          <Input
            id="recent-tabs-limit"
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
            <SelectTrigger className="sm:w-52" aria-label={t("interface.language")}>
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
            <SearchableCombobox
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
            <SelectTrigger className="sm:w-52" aria-label={t("interface.weekStartsOn")}>
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
            <SelectTrigger className="sm:w-52" aria-label={t("interface.timeFormat.label")}>
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
            aria-label={t("interface.smartTaskTitles.label")}
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
            <SelectTrigger
              className="sm:w-52"
              aria-label={t("interface.taskCompletionVisualFeedback.label")}
            >
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
        >
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
            aria-label={t("interface.taskCompletionAudioFeedback.label")}
          />
        </SettingsRow>

        <SettingsRow
          label={t("interface.taskCompletionHapticFeedback.label")}
          description={t("interface.taskCompletionHapticFeedback.description")}
        >
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
            aria-label={t("interface.taskCompletionHapticFeedback.label")}
          />
        </SettingsRow>
      </SettingsSection>

      {/* Kept by this browser or this computer rather than the account. */}
      <SettingsSection
        title={t("interface.deviceTitle")}
        description={t("interface.deviceDescription")}
      >
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
            aria-label={t("interface.keepScreenAwake.label")}
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
              aria-label={t("interface.desktopAutoUpdate.label")}
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
              aria-label={t("interface.desktopKeepRunning.label")}
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
              aria-label={t("interface.desktopOpenAtLogin.label")}
            />
          </SettingsRow>
        ) : null}
      </SettingsSection>
    </div>
  );
};
