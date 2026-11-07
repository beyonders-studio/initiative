/**
 * A clock, or a timer — one widget, switched from its title row.
 *
 * The clock reads the time here and, if the reader asked, in a few other
 * places: the venue's, the volunteer in another country's.
 *
 * The timer counts down from a length the reader picks. A running timer keeps
 * the moment it ends in the widget's options rather than in the page, so it is
 * still running after a reload, and on the reader's phone.
 */

import {
  AlarmClock,
  Clock,
  Pause,
  Play,
  RotateCcw,
  Timer,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import timerBeepUrl from "@/assets/beeps.wav";
import { HomeWidgetCard } from "@/components/home/HomeWidgetCard";
import { toast } from "@/lib/mascotToast";
import { isKnownTimezone, TIMEZONE_OPTIONS } from "@/lib/timezones";
import { Button } from "@/ui/button";
import { useTimeFormat } from "@/ui/host";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { dateTimeFormat, numberFormat } from "@/ui/lib/intl";
import { hour12Option } from "@/ui/lib/timeFormat";
import { cn } from "@/ui/lib/utils";
import { SearchableCombobox } from "@/ui/searchable-combobox";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";

import type { HomeWidgetProps, HomeWidgetSettingsProps } from "./types";

type Mode = "clock" | "timer";

export const MAX_CLOCK_ZONES = 3;
const TIMER_PRESETS = [5, 15, 25, 45] as const;
const DEFAULT_TIMER_MINUTES = 25;
const MAX_TIMER_MINUTES = 24 * 60;

interface TimerState {
  /** The length, in seconds. */
  duration: number;
  /** When a running timer ends, in epoch milliseconds. */
  endsAt?: number;
  /** What a paused timer has left, in seconds. */
  left?: number;
}

const modeOf = (options: Record<string, unknown>): Mode =>
  options.mode === "timer" ? "timer" : "clock";

const zonesOf = (options: Record<string, unknown>): string[] =>
  Array.isArray(options.zones)
    ? options.zones
        .filter((zone): zone is string => typeof zone === "string" && isKnownTimezone(zone))
        .slice(0, MAX_CLOCK_ZONES)
    : [];

const timerOf = (options: Record<string, unknown>): TimerState => {
  const raw = (options.timer ?? {}) as Record<string, unknown>;
  const whole = (value: unknown) =>
    typeof value === "number" && Number.isFinite(value) && value > 0 ? value : undefined;
  return {
    duration: Math.min(whole(raw.duration) ?? DEFAULT_TIMER_MINUTES * 60, MAX_TIMER_MINUTES * 60),
    endsAt: whole(raw.endsAt),
    left: whole(raw.left),
  };
};

/** The time now, read again every second while anything is showing it. */
const useNow = () => {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
};

/** "Asia/Kolkata" as "Kolkata". */
const placeName = (zone: string) => (zone.split("/").pop() ?? zone).replaceAll("_", " ");

/** Minutes a zone is ahead of UTC at a moment. */
const zoneOffset = (zone: string, at: Date): number => {
  const part = dateTimeFormat("en-US", { timeZone: zone, timeZoneName: "longOffset" })
    .formatToParts(at)
    .find((each) => each.type === "timeZoneName")?.value;
  const match = part?.match(/GMT([+-])(\d{2}):(\d{2})/);
  if (!match) return 0;
  const minutes = Number(match[2]) * 60 + Number(match[3]);
  return match[1] === "-" ? -minutes : minutes;
};

/**
 * A typed length, in seconds: `25` is minutes, `5:30` minutes and seconds,
 * `1:05:00` hours too. Null for anything else, or outside a second to a day.
 */
export const parseDuration = (text: string): number | null => {
  const parts = text.trim().split(":");
  if (parts.length > 3 || parts.some((part) => !/^\d+$/.test(part))) return null;
  const [a, b, c] = parts.map(Number);
  const seconds =
    parts.length === 1 ? a * 60 : parts.length === 2 ? a * 60 + b : a * 3600 + b * 60 + c;
  return seconds >= 1 && seconds <= MAX_TIMER_MINUTES * 60 ? seconds : null;
};

/** A count of seconds as 25:00, or 1:02:03 past the hour. */
const formatDuration = (seconds: number) => {
  const whole = Math.max(Math.ceil(seconds), 0);
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = whole % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
};

/** The finished timer's beep, made once and rewound for each play. */
let beepAudio: HTMLAudioElement | null = null;

/** Beep for a finished timer. Silent where the browser plays nothing. */
const beep = () => {
  try {
    beepAudio ??= new Audio(timerBeepUrl);
    beepAudio.currentTime = 0;
    void beepAudio.play().catch(() => {
      // Nothing played (no interaction yet, or no audio); the toast says it instead.
    });
  } catch {
    // No audio here; the toast says it instead.
  }
};

/** Whether the reader turned the timer's sound off. */
const mutedOf = (options: Record<string, unknown>): boolean => options.muted === true;

export const ClockWidget = ({ options, onOptionsChange }: HomeWidgetProps) => {
  const { t } = useTranslation("home");
  const mode = modeOf(options);
  const muted = mutedOf(options);

  return (
    <HomeWidgetCard
      icon={mode === "timer" ? Timer : Clock}
      title={t(`widgets.clock.${mode}`)}
      actions={
        <div className="flex items-center gap-1">
          {mode === "timer" ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-8"
              aria-pressed={muted}
              aria-label={muted ? t("widgets.clock.unmute") : t("widgets.clock.mute")}
              title={muted ? t("widgets.clock.unmute") : t("widgets.clock.mute")}
              onClick={() => {
                const { muted: _was, ...rest } = options;
                onOptionsChange(muted ? rest : { ...rest, muted: true });
              }}
            >
              {muted ? (
                <VolumeX className="size-4" aria-hidden="true" />
              ) : (
                <Volume2 className="size-4" aria-hidden="true" />
              )}
            </Button>
          ) : null}
          <ToggleGroup
            type="single"
            size="sm"
            value={mode}
            onValueChange={(next) => {
              if (next) onOptionsChange({ ...options, mode: next });
            }}
            aria-label={t("widgets.clock.mode")}
          >
            <ToggleGroupItem value="clock" aria-label={t("widgets.clock.clock")}>
              <Clock className="size-4" />
            </ToggleGroupItem>
            <ToggleGroupItem value="timer" aria-label={t("widgets.clock.timer")}>
              <Timer className="size-4" />
            </ToggleGroupItem>
          </ToggleGroup>
        </div>
      }
    >
      {mode === "timer" ? (
        <TimerFace options={options} onOptionsChange={onOptionsChange} />
      ) : (
        <ClockFace zones={zonesOf(options)} />
      )}
    </HomeWidgetCard>
  );
};

function ClockFace({ zones }: { zones: string[] }) {
  const { t, i18n } = useTranslation("home");
  const locale = i18n.resolvedLanguage ?? i18n.language;
  // Subscribed, so switching between 12 and 24 hours redraws the clock at once.
  useTimeFormat();
  const now = new Date(useNow());
  const time = (zone?: string) =>
    dateTimeFormat(locale, {
      hour: "numeric",
      minute: "2-digit",
      hour12: hour12Option(),
      ...(zone ? { timeZone: zone } : {}),
    }).format(now);
  const day = (zone?: string) =>
    dateTimeFormat(locale, { weekday: "short", ...(zone ? { timeZone: zone } : {}) }).format(now);
  const here = -now.getTimezoneOffset();
  const hours = numberFormat(locale, {
    style: "unit",
    unit: "hour",
    unitDisplay: "short",
    maximumFractionDigits: 2,
  });

  return (
    <div className="flex h-full flex-col justify-center gap-3">
      <div>
        <p className="font-semibold text-4xl tabular-nums tracking-tight">{time()}</p>
        <p className="text-muted-foreground text-sm">
          {dateTimeFormat(locale, { weekday: "long", month: "long", day: "numeric" }).format(now)}
        </p>
      </div>
      {zones.length > 0 ? (
        <ul className="space-y-1 border-t pt-2">
          {zones.map((zone) => {
            const difference = (zoneOffset(zone, now) - here) / 60;
            const otherDay = day(zone) !== day();
            return (
              <li key={zone} className="flex items-baseline justify-between gap-2 text-sm">
                <span className="min-w-0 truncate">{placeName(zone)}</span>
                <span className="shrink-0 text-muted-foreground text-xs">
                  {difference === 0
                    ? t("widgets.clock.sameTime")
                    : t(difference > 0 ? "widgets.clock.ahead" : "widgets.clock.behind", {
                        offset: hours.format(Math.abs(difference)),
                      })}
                </span>
                <span className="shrink-0 font-medium tabular-nums">
                  {time(zone)}
                  {otherDay ? (
                    <span className="ml-1 text-muted-foreground text-xs">{day(zone)}</span>
                  ) : null}
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

function TimerFace({
  options,
  onOptionsChange,
}: Pick<HomeWidgetProps, "options" | "onOptionsChange">) {
  const { t } = useTranslation("home");
  const timer = timerOf(options);
  const muted = mutedOf(options);
  const now = useNow();
  const running = timer.endsAt !== undefined;
  const paused = !running && timer.left !== undefined;
  const remaining = running
    ? ((timer.endsAt as number) - now) / 1000
    : paused
      ? (timer.left as number)
      : timer.duration;
  const done = running && remaining <= 0;
  const progress = Math.min(Math.max(1 - remaining / timer.duration, 0), 1);

  // Said once, when it runs out while somebody is looking — not again on
  // every reload of a timer that finished overnight.
  const wasRunning = useRef(running && !done);
  useEffect(() => {
    if (done && wasRunning.current) {
      if (!muted) beep();
      toast.success(t("widgets.clock.timeUp"), { id: "home-timer-done" });
    }
    wasRunning.current = running && !done;
  }, [done, running, muted, t]);

  const save = (next: TimerState) =>
    onOptionsChange({
      ...options,
      timer: {
        duration: next.duration,
        ...(next.endsAt ? { endsAt: next.endsAt } : {}),
        ...(next.left ? { left: next.left } : {}),
      },
    });
  const start = (seconds: number) =>
    save({ duration: timer.duration, endsAt: Date.now() + seconds * 1000 });

  // What is being typed onto the face, while it is.
  const idle = !running && !paused;
  const [draft, setDraft] = useState<string | null>(null);
  const saveDraft = () => {
    const seconds = draft === null ? null : parseDuration(draft);
    if (seconds !== null) save({ duration: seconds });
    setDraft(null);
  };

  return (
    <div className="flex h-full flex-col items-center justify-center gap-3">
      <div className="relative flex w-full flex-col items-center gap-2">
        {draft !== null ? (
          <Input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            aria-label={t("widgets.clock.typeLength")}
            aria-invalid={parseDuration(draft) === null}
            className="h-auto w-40 py-0 text-center font-semibold text-4xl tabular-nums tracking-tight md:text-4xl"
            inputMode="numeric"
            autoFocus
            onFocus={(event) => event.target.select()}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                saveDraft();
              }
              if (event.key === "Escape") setDraft(null);
            }}
            onBlur={saveDraft}
          />
        ) : idle ? (
          // Set, not running: the length is typed straight onto the face.
          <button
            type="button"
            title={t("widgets.clock.typeLength")}
            aria-label={t("widgets.clock.typeLengthOf", { length: formatDuration(remaining) })}
            onClick={() => setDraft(formatDuration(timer.duration))}
            className="cursor-text rounded-md px-1 font-semibold text-4xl tabular-nums tracking-tight hover:bg-foreground/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {formatDuration(remaining)}
          </button>
        ) : (
          <p
            className={cn(
              "font-semibold text-4xl tabular-nums tracking-tight",
              done && "animate-pulse text-primary"
            )}
            role="timer"
          >
            {done ? t("widgets.clock.timeUpShort") : formatDuration(remaining)}
          </p>
        )}
        <div className="h-1 w-full max-w-60 overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-primary" style={{ width: `${progress * 100}%` }} />
        </div>
      </div>

      {idle ? (
        <div className="flex flex-wrap justify-center gap-1">
          {TIMER_PRESETS.map((minutes) => (
            <Button
              key={minutes}
              type="button"
              size="sm"
              variant={timer.duration === minutes * 60 ? "secondary" : "ghost"}
              className="h-7 px-2 text-xs"
              onClick={() => save({ duration: minutes * 60 })}
            >
              {t("widgets.clock.minutes", { count: minutes })}
            </Button>
          ))}
        </div>
      ) : null}

      <div className="flex gap-2">
        {done ? (
          <Button type="button" size="sm" onClick={() => save({ duration: timer.duration })}>
            <X className="size-4" aria-hidden="true" />
            {t("widgets.clock.dismiss")}
          </Button>
        ) : running ? (
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => save({ duration: timer.duration, left: Math.max(remaining, 1) })}
          >
            <Pause className="size-4" aria-hidden="true" />
            {t("widgets.clock.pause")}
          </Button>
        ) : (
          <Button type="button" size="sm" onClick={() => start(remaining)}>
            <Play className="size-4" aria-hidden="true" />
            {paused ? t("widgets.clock.resume") : t("widgets.clock.start")}
          </Button>
        )}
        {(running || paused) && !done ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => save({ duration: timer.duration })}
          >
            <RotateCcw className="size-4" aria-hidden="true" />
            {t("widgets.clock.reset")}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

export const ClockSettings = ({ options, onChange }: HomeWidgetSettingsProps) => {
  const { t } = useTranslation(["home", "settings"]);
  const zones = zonesOf(options);
  const timer = timerOf(options);
  const [minutes, setMinutes] = useState(String(Math.round(timer.duration / 60)));

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <Label>{t("widgets.clock.zones")}</Label>
        {zones.length > 0 ? (
          <ul className="space-y-1">
            {zones.map((zone) => (
              <li key={zone} className="flex items-center justify-between gap-2 text-sm">
                <span className="truncate">{zone}</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-8"
                  aria-label={t("widgets.clock.removeZone", { zone: placeName(zone) })}
                  onClick={() =>
                    onChange({ ...options, zones: zones.filter((each) => each !== zone) })
                  }
                >
                  <X className="size-4" />
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
        {zones.length < MAX_CLOCK_ZONES ? (
          <SearchableCombobox
            items={TIMEZONE_OPTIONS.filter((zone) => !zones.includes(zone)).map((zone) => ({
              value: zone,
              label: zone,
            }))}
            value=""
            onValueChange={(zone) => {
              if (zone) onChange({ ...options, zones: [...zones, zone] });
            }}
            placeholder={t("widgets.clock.addZone")}
            emptyMessage={t("settings:profile.timezoneEmpty")}
            aria-label={t("widgets.clock.addZone")}
          />
        ) : null}
      </div>

      <div className="space-y-2">
        <Label htmlFor="clock-widget-minutes" className="flex items-center gap-1.5">
          <AlarmClock className="size-4 text-muted-foreground" aria-hidden="true" />
          {t("widgets.clock.length")}
        </Label>
        <Input
          id="clock-widget-minutes"
          type="number"
          inputMode="numeric"
          min={1}
          max={MAX_TIMER_MINUTES}
          value={minutes}
          onChange={(event) => {
            setMinutes(event.target.value);
            const value = Math.round(Number(event.target.value));
            if (value >= 1 && value <= MAX_TIMER_MINUTES) {
              // A new length starts the timer over.
              onChange({ ...options, timer: { duration: value * 60 } });
            }
          }}
        />
      </div>
    </div>
  );
};
