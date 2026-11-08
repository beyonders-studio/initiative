/**
 * The top of the page: hello, today's date, and how much is due — said by
 * Yonder, unless the reader would rather he sat this one out.
 *
 * A brand-new account is welcomed rather than wished a good morning.
 */

import { endOfDay, startOfDay } from "date-fns";
import { AlarmClock, CalendarCheck, PartyPopper } from "lucide-react";
import { useTranslation } from "react-i18next";

import { type YonderPose, YonderSays } from "@/components/start/YonderSays";
import { useAuth } from "@/hooks/useAuth";
import { useOpenTaskCount } from "@/hooks/useOpenTaskCount";
import { getUserDisplayName } from "@/lib/userDisplay";
import { Badge } from "@/ui/badge";
import { Label } from "@/ui/label";
import { dateTimeFormat } from "@/ui/lib/intl";
import { useLiveClockValue } from "@/ui/lib/useRelativeTime";
import { Switch } from "@/ui/switch";

import type { HomeWidgetProps, HomeWidgetSettingsProps } from "./types";

/** How long an account counts as new: its first day. */
const NEW_ACCOUNT_MS = 24 * 60 * 60 * 1000;

const showsYonder = (options: Record<string, unknown>) => options.yonder !== false;

type PartOfDay = "morning" | "afternoon" | "evening" | "night";

const partOfDay = (hour: number): PartOfDay =>
  hour < 5
    ? "night"
    : hour < 12
      ? "morning"
      : hour < 18
        ? "afternoon"
        : hour < 22
          ? "evening"
          : "night";

export const GreetingWidget = ({ options }: HomeWidgetProps) => {
  const { t, i18n } = useTranslation("home");
  const { user } = useAuth();
  const locale = i18n.resolvedLanguage ?? i18n.language;

  // Re-rendered when the hour turns, not every tick: the greeting changes with
  // the part of the day, and the counts with the day itself.
  const hourStart = useLiveClockValue((now) => {
    const at = new Date(now);
    at.setMinutes(0, 0, 0);
    return at.getTime();
  });
  const now = new Date(hourStart);
  const todayStart = startOfDay(now).toISOString();
  const todayEnd = endOfDay(now).toISOString();

  const overdue = useOpenTaskCount(null, todayStart);
  const dueToday = useOpenTaskCount(todayStart, todayEnd);

  const name = getUserDisplayName(user);
  const date = dateTimeFormat(locale, { weekday: "long", month: "long", day: "numeric" }).format(
    now
  );
  const loaded = overdue.data !== undefined && dueToday.data !== undefined;
  const clear = loaded && overdue.data === 0 && dueToday.data === 0;
  const isNew = user ? hourStart - Date.parse(user.created_at) < NEW_ACCOUNT_MS : false;

  // He reads the day: puzzling over what is late, waving at a clear one.
  const pose: YonderPose = isNew
    ? "excited"
    : overdue.data
      ? "thinking"
      : clear
        ? "proud"
        : dueToday.data
          ? "talking"
          : "idle";

  return (
    <section className="flex h-full items-center gap-3 px-1">
      {showsYonder(options) ? (
        <div className="shrink-0">
          <YonderSays pose={pose} />
        </div>
      ) : null}
      <div className="flex min-w-0 flex-col justify-center gap-2">
        <h2 className="text-balance break-words font-semibold text-2xl tracking-tight sm:text-3xl">
          {isNew
            ? t("widgets.greeting.welcome", { name })
            : t(`widgets.greeting.${partOfDay(now.getHours())}`, { name })}
        </h2>
        <div className="flex flex-wrap items-center gap-2 text-muted-foreground text-sm">
          <span>{date}</span>
          {clear ? (
            <Badge variant="secondary" className="gap-1">
              <PartyPopper className="size-3" aria-hidden="true" />
              {t("widgets.greeting.clear")}
            </Badge>
          ) : null}
          {overdue.data ? (
            <Badge variant="secondary" className="gap-1">
              <AlarmClock className="size-3" aria-hidden="true" />
              {t("widgets.greeting.overdue", { count: overdue.data })}
            </Badge>
          ) : null}
          {dueToday.data ? (
            <Badge variant="secondary" className="gap-1">
              <CalendarCheck className="size-3" aria-hidden="true" />
              {t("widgets.greeting.dueToday", { count: dueToday.data })}
            </Badge>
          ) : null}
        </div>
      </div>
    </section>
  );
};

export const GreetingSettings = ({ options, onChange }: HomeWidgetSettingsProps) => {
  const { t } = useTranslation("home");
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="space-y-1">
        <Label htmlFor="greeting-widget-yonder">{t("widgets.greeting.yonder")}</Label>
        <p className="text-muted-foreground text-xs">{t("widgets.greeting.yonderHint")}</p>
      </div>
      <Switch
        id="greeting-widget-yonder"
        checked={showsYonder(options)}
        onCheckedChange={(checked) => onChange({ ...options, yonder: checked })}
      />
    </div>
  );
};
