import { MessageCircle } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { CustomStatusOutput, UserSelfUpdate } from "@/api/generated/initiativeAPI.schemas";
import { useUpdateCurrentUser } from "@/hooks/useUsers";
import { Button } from "@/ui/button";
import { EmojiField } from "@/ui/emoji-picker";
import { Input } from "@/ui/input";
import { cn } from "@/ui/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/ui/popover";

/** Mirrors ``STATUS_TEXT_MAX_LENGTH`` on the server. */
const STATUS_MAX_LENGTH = 40;

/** Nothing said: neither an emoji nor a line. */
export const isStatusEmpty = (status: CustomStatusOutput) => !status.emoji && !status.text;

/**
 * The bubble itself, which is all a reader of someone else's profile gets.
 *
 * A thought bubble rather than a speech one: a status is what someone is
 * thinking about, not something they said to you. So the tail is two dots
 * shrinking toward the picture below the bubble, which is the face thinking it.
 *
 * Exported because the account menu draws it over the banner, where the bubble
 * is the whole of what a status looks like and the editor is somewhere else.
 */
export const StatusBubble = ({
  status,
  muted,
  className,
}: {
  status: CustomStatusOutput;
  muted?: boolean;
  className?: string;
}) => {
  const { t } = useTranslation("profiles");
  // Offset from the left edge so it reads as coming from the picture rather
  // than from the corner of the box, and set on a diagonal so the pair points
  // at the face instead of running flat beside the bubble. The near dot tucks
  // into the bubble's edge — the bubble is positioned, so it paints over what
  // it covers — because a tail that clears the body reads as three loose
  // circles rather than one thought.
  const dots = (
    <span aria-hidden="true" className="-mt-1 flex items-center gap-0.5 pl-4">
      <span className="block size-1.5 translate-y-1 rounded-full border bg-card" />
      <span className="block size-2.5 rounded-full border bg-card" />
    </span>
  );
  return (
    <span className={cn("inline-block max-w-full text-left", className)}>
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
 * Saying what you're up to.
 *
 * The form on its own, so the same editor opens from the bubble on your own
 * profile and from the account menu in the sidebar, where the status is a line
 * under your name with no bubble to click. The emoji and the line are set
 * together, because they are one thing and either half may be left out.
 */
export const StatusEditor = ({
  status,
  onSaved,
  onDone,
}: {
  status: CustomStatusOutput;
  onSaved?: () => Promise<void> | void;
  /** Close whatever is holding the form, once a change is saved. */
  onDone?: () => void;
}) => {
  const { t } = useTranslation(["profiles", "common"]);
  const [emoji, setEmoji] = useState(status.emoji ?? null);
  const [text, setText] = useState(status.text ?? "");

  const [prevStatus, setPrevStatus] = useState(status);
  if (prevStatus.emoji !== status.emoji || prevStatus.text !== status.text) {
    setPrevStatus(status);
    setEmoji(status.emoji ?? null);
    setText(status.text ?? "");
  }

  const save = useUpdateCurrentUser(
    {
      onSuccess: async () => {
        onDone?.();
        await onSaved?.();
      },
    },
    "profiles:status.failed"
  );

  const commit = (next: { emoji: string | null; text: string | null }) =>
    save.mutate({ custom_status: next } as UserSelfUpdate);

  return (
    <>
      <div className="space-y-1">
        <p className="font-medium text-sm">{t("profiles:status.edit")}</p>
        <p className="text-muted-foreground text-xs">{t("profiles:status.help")}</p>
      </div>
      <div className="flex gap-2">
        <div className="w-28 shrink-0">
          <EmojiField
            id="profile-status-emoji"
            value={emoji}
            onChange={setEmoji}
            placeholder={t("profiles:status.emojiPlaceholder")}
          />
        </div>
        <Input
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={t("profiles:status.placeholder")}
          maxLength={STATUS_MAX_LENGTH}
          aria-label={t("profiles:status.placeholder")}
        />
      </div>
      <div className="flex justify-between gap-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={save.isPending || isStatusEmpty(status)}
          onClick={() => commit({ emoji: null, text: null })}
        >
          {t("profiles:status.clear")}
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={save.isPending}
          onClick={() => commit({ emoji, text: text || null })}
        >
          {save.isPending ? t("common:submitting") : t("profiles:status.save")}
        </Button>
      </div>
    </>
  );
};

/**
 * What someone is up to, in their own words.
 *
 * A bubble rather than a line of text, because it is a thing a person said
 * rather than a field of their record — and on your own profile it is the
 * control too: the whole point of a status is that you change it as often as
 * it changes, so it is edited where it is read instead of on a form somewhere
 * else.
 */
export const ProfileStatus = ({
  status,
  editable = false,
  onSaved,
  className,
}: {
  status: CustomStatusOutput;
  /** Whether this is your own profile, and the bubble opens an editor. */
  editable?: boolean;
  onSaved?: () => Promise<void> | void;
  className?: string;
}) => {
  const { t } = useTranslation("profiles");
  const [open, setOpen] = useState(false);

  if (!editable) {
    if (isStatusEmpty(status)) return null;
    return <StatusBubble status={status} className={className} />;
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "rounded-2xl text-left transition-opacity hover:opacity-80 focus-visible:outline-2 focus-visible:outline-ring",
            className
          )}
          aria-label={t("status.edit")}
        >
          <StatusBubble status={status} muted={isStatusEmpty(status)} />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 space-y-3">
        <StatusEditor status={status} onSaved={onSaved} onDone={() => setOpen(false)} />
      </PopoverContent>
    </Popover>
  );
};
