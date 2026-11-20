import { addHours, addMinutes, endOfDay, endOfWeek } from "date-fns";
import { MessageCircle, SmilePlus, X } from "lucide-react";
import { useEffect, useReducer, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CustomStatusInput,
  CustomStatusOutput,
  UserSelfUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { useReadMyNotificationPreferences } from "@/api/generated/notifications/notifications";
import { useUpdateNotificationPreferences } from "@/hooks/useNotificationPreferences";
import { useUpdateCurrentUser } from "@/hooks/useUsers";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { DateTimePicker } from "@/ui/date-time-picker";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import {
  EmojiPicker,
  EmojiPickerContent,
  EmojiPickerFooter,
  EmojiPickerSearch,
} from "@/ui/emoji-picker";
import { Field } from "@/ui/field";
import { useWeekStart, type WeekStart } from "@/ui/host";
import { Input } from "@/ui/input";
import { formatDateTime } from "@/ui/lib/formatDate";
import { fromPickerValue, toPickerValue } from "@/ui/lib/localDateTime";
import { cn } from "@/ui/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Switch } from "@/ui/switch";

/** Mirrors ``STATUS_TEXT_MAX_LENGTH`` on the server. */
const STATUS_MAX_LENGTH = 40;

/**
 * Nothing to show: neither an emoji nor a line, or a status whose end has
 * passed. The server reads an ended status as none too; this covers the time
 * between its end and the next read.
 */
const isStatusEmpty = (status: CustomStatusInput) =>
  (!status.emoji && !status.text) ||
  (!!status.clear_at && Date.parse(status.clear_at) <= Date.now());

/**
 * `isStatusEmpty`, asked again the moment the status ends, so a page left
 * open drops it then rather than at its next fetch.
 */
export const useStatusEmpty = (status: CustomStatusInput | null | undefined) => {
  const [checks, recheck] = useReducer((count: number) => count + 1, 0);
  const empty = !status || isStatusEmpty(status);
  const end = status?.clear_at ? Date.parse(status.clear_at) : null;
  useEffect(() => {
    if (empty || end === null) return;
    // A timer holds about 24 days at most; a later end is asked about again
    // when that runs out.
    const timer = setTimeout(recheck, Math.min(end - Date.now(), 2 ** 31 - 1));
    return () => clearTimeout(timer);
  }, [empty, end, checks]);
  return empty;
};

/** When the status comes off, as words for a tooltip, or nothing. */
const useUntil = (status: CustomStatusInput | null | undefined) => {
  const { t } = useTranslation("profiles");
  return status?.clear_at ? t("status.until", { time: formatDateTime(status.clear_at) }) : "";
};

/**
 * The bubble itself, which is all a reader of someone else's profile gets.
 *
 * A thought bubble rather than a speech one: a status is what someone is
 * thinking about, not something they said to you. So the tail is two dots
 * shrinking toward the picture below the bubble, which is the face thinking it.
 */
export const StatusBubble = ({
  status,
  muted,
  className,
}: {
  status: CustomStatusInput;
  muted?: boolean;
  className?: string;
}) => {
  const { t } = useTranslation("profiles");
  const until = useUntil(status);
  // The near dot tucks into the bubble's edge, so the tail reads as one
  // thought rather than three loose circles.
  const dots = (
    <span aria-hidden="true" className="-mt-1 flex items-center gap-0.5 pl-4">
      <span className="block size-1.5 translate-y-1 rounded-full border bg-card" />
      <span className="block size-2.5 rounded-full border bg-card" />
    </span>
  );
  return (
    <span className={cn("inline-block max-w-full text-left", className)} title={until || undefined}>
      <span
        className={cn(
          "relative flex max-w-full items-center gap-2 rounded-[1.25rem] border bg-card px-3.5 py-2",
          muted && "text-muted-foreground"
        )}
      >
        {status.emoji ? (
          <span className="text-lg leading-none" aria-hidden="true">
            {status.emoji}
          </span>
        ) : (
          <MessageCircle className="size-4 shrink-0 opacity-60" aria-hidden="true" />
        )}
        <span className="min-w-0 break-words">{status.text || t("status.empty")}</span>
      </span>
      {dots}
    </span>
  );
};

/**
 * A status as one muted line beside a name: the emoji, then as much of the
 * line as fits. The whole of it, and when it ends, are in its tooltip.
 */
export const StatusLine = ({
  status,
  className,
}: {
  status: CustomStatusInput | null | undefined;
  className?: string;
}) => {
  const until = useUntil(status);
  const empty = useStatusEmpty(status);
  if (!status || empty) return null;
  const title = [[status.emoji, status.text].filter(Boolean).join(" "), until]
    .filter(Boolean)
    .join(" · ");
  return (
    <span
      className={cn("flex min-w-0 items-center gap-1 text-muted-foreground", className)}
      title={title}
    >
      {status.emoji ? <span className="shrink-0">{status.emoji}</span> : null}
      {status.text ? <span className="truncate">{status.text}</span> : null}
    </span>
  );
};

/** How long a status stays up. Every choice but `never` becomes a time. */
const CLEAR_AFTER = ["never", "30m", "1h", "4h", "today", "week", "custom"] as const;
type ClearAfter = (typeof CLEAR_AFTER)[number];

/** When a choice ends, counted from now; null for `never` or no picked time. */
const endOf = (choice: ClearAfter, custom: string, weekStartsOn: WeekStart): string | null => {
  const now = new Date();
  return {
    never: null,
    "30m": addMinutes(now, 30).toISOString(),
    "1h": addHours(now, 1).toISOString(),
    "4h": addHours(now, 4).toISOString(),
    today: endOfDay(now).toISOString(),
    week: endOfWeek(now, { weekStartsOn }).toISOString(),
    custom: fromPickerValue(custom),
  }[choice];
};

/** The common things to be up to, each with how long it usually lasts. */
const SUGGESTIONS = [
  { key: "meeting", emoji: "\u{1F4C5}", clearAfter: "1h" },
  { key: "commuting", emoji: "\u{1F68C}", clearAfter: "30m" },
  { key: "sick", emoji: "\u{1F912}", clearAfter: "today" },
  { key: "vacation", emoji: "\u{1F334}", clearAfter: "never" },
  { key: "remote", emoji: "\u{1F3E1}", clearAfter: "today" },
] as const satisfies readonly { key: string; emoji: string; clearAfter: ClearAfter }[];

/**
 * Saying what you're up to, and for how long.
 *
 * One dialog, opened from wherever your status shows: the line under your name
 * in the sidebar, the account menu, and the bubble on your own profile. With
 * nothing typed it offers the common answers; once something is, it asks when
 * the status should come off by itself, and whether to pause notifications
 * until then. The pause is the one My Settings books by the day, so either
 * place shows and ends the same pause.
 */
export const StatusDialog = ({
  open,
  onOpenChange,
  status,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  status: CustomStatusOutput;
  onSaved?: () => Promise<void> | void;
}) => {
  const { t } = useTranslation(["profiles", "common"]);
  const weekStartsOn = useWeekStart();
  const current = isStatusEmpty(status) ? null : status;
  const [emoji, setEmoji] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [clearAfter, setClearAfter] = useState<ClearAfter>("today");
  const [custom, setCustom] = useState("");
  const [picking, setPicking] = useState(false);
  // Null until the switch is moved: a pause booked elsewhere is shown, and is
  // only written over when somebody asks for that here.
  const [pauseChoice, setPauseChoice] = useState<boolean | null>(null);
  const preferences = useReadMyNotificationPreferences({ query: { enabled: open } });
  const booked = preferences.data?.pause;
  const pauseRunning = !!booked && Date.parse(booked.since) <= Date.now();
  const paused = pauseChoice ?? pauseRunning;
  const writePause = useUpdateNotificationPreferences();

  // Every opening starts from the status as it stands.
  const [wasOpen, setWasOpen] = useState(false);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setEmoji(current?.emoji ?? null);
      setText(current?.text ?? "");
      setClearAfter(current ? (current.clear_at ? "custom" : "never") : "today");
      setCustom(toPickerValue(current?.clear_at));
      setPauseChoice(null);
    }
  }

  const save = useUpdateCurrentUser(undefined, "profiles:status.failed");
  const saving = save.isPending || writePause.isPending;

  // What the form shows; the end that is saved is counted again at Save, so
  // time spent in the dialog does not come off the status.
  const now = new Date();
  const clearAt = endOf(clearAfter, custom, weekStartsOn);
  const passed = (end: string | null) => end !== null && Date.parse(end) <= Date.now();
  const blank = !emoji && !text.trim();
  const customMissing = clearAfter === "custom" && (clearAt === null || passed(clearAt));
  // A pause always ends, so it needs a status that does.
  const pauseNeedsEnd = !blank && pauseChoice === true && clearAt === null;

  /** Save the status, then the pause, and close only once both stand. A
   *  status that fails leaves the pause alone; a pause that fails after the
   *  status saved says so and stays open to try again. */
  const commit = async (next: CustomStatusInput | null, pause: boolean | null) => {
    try {
      await save.mutateAsync({ custom_status: next } as UserSelfUpdate);
    } catch {
      return;
    }
    await onSaved?.();
    if (pause !== null && (pause || pauseRunning)) {
      try {
        await writePause.mutateAsync(
          pause ? { pause_until: next?.clear_at ?? null } : { clear_pause: true }
        );
      } catch (error) {
        toast.error(getErrorMessage(error, "profiles:status.pause.failed"));
        return;
      }
    }
    onOpenChange(false);
  };

  const submit = () => {
    const end = endOf(clearAfter, custom, weekStartsOn);
    if (clearAfter === "custom" && (end === null || passed(end))) return;
    if (blank) return commit(null, null);
    return commit({ emoji, text: text.trim() || null, clear_at: end }, pauseChoice);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("profiles:status.edit")}</DialogTitle>
          <DialogDescription>{t("profiles:status.help")}</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="flex items-center gap-1 rounded-md border bg-background pr-1 focus-within:ring-2 focus-within:ring-ring">
            <Popover open={picking} onOpenChange={setPicking}>
              <PopoverTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="shrink-0 text-lg"
                  aria-label={t("profiles:status.emojiPlaceholder")}
                >
                  {emoji ?? <SmilePlus className="size-4 text-muted-foreground" />}
                </Button>
              </PopoverTrigger>
              {/* Capped at the room Radix measured, so a phone's keyboard
                  shrinks the list rather than pushing it off screen. */}
              <PopoverContent
                className="flex w-fit flex-col overflow-hidden p-0"
                align="start"
                collisionPadding={8}
              >
                <EmojiPicker
                  className="h-[340px]"
                  onEmojiSelect={({ emoji: picked }) => {
                    setEmoji(picked);
                    setPicking(false);
                  }}
                >
                  <EmojiPickerSearch />
                  <EmojiPickerContent />
                  <EmojiPickerFooter />
                </EmojiPicker>
              </PopoverContent>
            </Popover>
            <Input
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder={t("profiles:status.placeholder")}
              maxLength={STATUS_MAX_LENGTH}
              aria-label={t("profiles:status.placeholder")}
              className="border-0 px-1 shadow-none focus-visible:ring-0"
            />
            {blank ? null : (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7 shrink-0"
                aria-label={t("profiles:status.erase")}
                onClick={() => {
                  setEmoji(null);
                  setText("");
                }}
              >
                <X className="size-4" />
              </Button>
            )}
          </div>

          {blank ? (
            <div className="space-y-1">
              <p className="font-medium text-muted-foreground text-xs">
                {t("profiles:status.suggestions")}
              </p>
              <ul className="-mx-2">
                {SUGGESTIONS.map((suggestion) => {
                  const words = t(`profiles:status.suggestion.${suggestion.key}`);
                  return (
                    <li key={suggestion.key}>
                      <button
                        type="button"
                        className="flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
                        onClick={() => {
                          setEmoji(suggestion.emoji);
                          setText(words);
                          setClearAfter(suggestion.clearAfter);
                        }}
                      >
                        <span className="text-lg leading-none">{suggestion.emoji}</span>
                        <span>{words}</span>
                        <span className="text-muted-foreground">
                          · {t(`profiles:status.clearAfter.${suggestion.clearAfter}`)}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : (
            <div className="space-y-2">
              <Field label={t("profiles:status.clearAfter.label")}>
                <Select
                  value={clearAfter}
                  onValueChange={(value) => setClearAfter(value as ClearAfter)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CLEAR_AFTER.map((choice) => (
                      <SelectItem key={choice} value={choice}>
                        {t(`profiles:status.clearAfter.${choice}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              {clearAfter === "custom" ? (
                <DateTimePicker
                  value={custom}
                  onChange={setCustom}
                  calendarProps={{ disabled: { before: now } }}
                />
              ) : null}
              <div className="flex items-start justify-between gap-4 pt-2">
                <span className="space-y-0.5">
                  <label htmlFor="status-pause" className="block font-medium text-sm">
                    {t("profiles:status.pause.label")}
                  </label>
                  <span className="block text-muted-foreground text-xs">
                    {pauseChoice === null && pauseRunning && booked
                      ? t("profiles:status.pause.running", {
                          time: formatDateTime(booked.until),
                        })
                      : clearAt === null
                        ? t("profiles:status.pause.needsEnd")
                        : t("profiles:status.pause.help")}
                  </span>
                </span>
                <Switch
                  id="status-pause"
                  checked={paused}
                  onCheckedChange={setPauseChoice}
                  disabled={!paused && clearAt === null}
                />
              </div>
            </div>
          )}
        </DialogBody>
        <DialogFooter
          submitLabel={t("profiles:status.save")}
          pendingLabel={t("common:submitting")}
          onSubmit={submit}
          pending={saving}
          disabled={customMissing || pauseNeedsEnd}
        >
          {current ? (
            <Button
              type="button"
              variant="ghost"
              className="sm:mr-auto"
              disabled={saving}
              onClick={() => commit(null, null)}
            >
              {t("profiles:status.clear")}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

/**
 * What someone is up to, in their own words.
 *
 * A bubble rather than a line of text, because it is a thing a person said
 * rather than a field of their record. On your own profile it is the control
 * too, so a status is changed where it is read.
 */
export const ProfileStatus = ({
  status,
  editable = false,
  onSaved,
  className,
}: {
  status: CustomStatusOutput;
  /** Whether this is your own profile, and the bubble opens the editor. */
  editable?: boolean;
  onSaved?: () => Promise<void> | void;
  className?: string;
}) => {
  const { t } = useTranslation("profiles");
  const [open, setOpen] = useState(false);
  const empty = useStatusEmpty(status);

  if (!editable) {
    if (empty) return null;
    return <StatusBubble status={status} className={className} />;
  }

  return (
    <>
      <button
        type="button"
        className={cn(
          "rounded-2xl text-left transition-opacity hover:opacity-80 focus-visible:outline-2 focus-visible:outline-ring",
          className
        )}
        aria-label={t("status.edit")}
        onClick={() => setOpen(true)}
      >
        <StatusBubble status={empty ? {} : status} muted={empty} />
      </button>
      <StatusDialog open={open} onOpenChange={setOpen} status={status} onSaved={onSaved} />
    </>
  );
};
