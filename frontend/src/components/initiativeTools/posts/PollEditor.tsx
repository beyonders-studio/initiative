import { Plus, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { PollRead, PollWrite } from "@/api/generated/initiativeAPI.schemas";
import { fromLocalDateTimeInput, toLocalDateTimeInput } from "@/lib/formatDate";
import { MAX_POLL_OPTION_CHARS, MAX_POLL_OPTIONS, MIN_POLL_OPTIONS } from "@/lib/posts";
import { Button } from "@/ui/button";
import { DateTimePicker } from "@/ui/date-time-picker";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Switch } from "@/ui/switch";

/**
 * A poll while it is being written.
 *
 * Choices are plain strings rather than the `{ text }` objects the API takes,
 * and the close time is the picker's local string rather than an instant —
 * both because this is what somebody is typing, not what the server stores.
 * The two are converted at the edge, in `pollDraftToWrite`.
 */
export type PollDraft = {
  question: string;
  options: string[];
  allowsMultiple: boolean;
  isAnonymous: boolean;
  hideResults: boolean;
  closesAt: string;
};

export const emptyPollDraft = (): PollDraft => ({
  question: "",
  // Two empty rows, because the shortest poll that is still a poll offers a
  // choice — starting with one would ask somebody to discover the "add" button
  // before they could write anything valid.
  options: ["", ""],
  allowsMultiple: false,
  isAnonymous: false,
  hideResults: false,
  closesAt: "",
});

export const pollDraftFromRead = (poll: PollRead): PollDraft => ({
  question: poll.question ?? "",
  options: poll.options.map((option) => option.text),
  allowsMultiple: poll.allows_multiple,
  isAnonymous: poll.is_anonymous,
  hideResults: poll.hide_results,
  closesAt: toLocalDateTimeInput(poll.closes_at),
});

/** The choices as the server will see them — trimmed, with the empty rows
 *  somebody left behind dropped rather than sent. */
const filledOptions = (draft: PollDraft) =>
  draft.options.map((option) => option.trim()).filter((option) => option.length > 0);

/**
 * Two choices that say the same thing, as nearly as the browser can tell.
 *
 * The server compares with Python's `casefold`, which is full Unicode case
 * folding — it maps `ß` to `ss`, where JavaScript's lowercasing does not. There
 * is no `casefold` here to match it with, so this is the close approximation:
 * normalize, then lowercase. A pair it misses is refused by the API with
 * `POST_POLL_DUPLICATE_CHOICE`, which the composer shows as a sentence — the
 * point of this check is to answer the common case without a round trip, not
 * to be the authority.
 */
const foldChoice = (text: string) => text.normalize("NFKC").toLocaleLowerCase();

/**
 * Whether this draft is a poll yet.
 *
 * The same three rules the server holds it to, asked here so the submit button
 * can say no before the round trip: enough choices, not too many, and no two
 * saying the same thing.
 */
export const isPollDraftValid = (draft: PollDraft): boolean => {
  const options = filledOptions(draft);
  if (options.length < MIN_POLL_OPTIONS || options.length > MAX_POLL_OPTIONS) return false;
  return new Set(options.map(foldChoice)).size === options.length;
};

export const pollDraftToWrite = (draft: PollDraft): PollWrite => ({
  question: draft.question.trim() || null,
  options: filledOptions(draft).map((text) => ({ text })),
  allows_multiple: draft.allowsMultiple,
  is_anonymous: draft.isAnonymous,
  hide_results: draft.hideResults,
  closes_at: fromLocalDateTimeInput(draft.closesAt),
});

interface PollEditorProps {
  value: PollDraft;
  onChange: (draft: PollDraft) => void;
  /** Removes the poll entirely. Absent where there is nothing to remove. */
  onRemove?: () => void;
  /** True once somebody has answered: the choices are then frozen, because a
   *  ballot cast for one must not become a ballot for whatever replaces it.
   *  The server refuses the change either way; this stops it being offered. */
  choicesLocked?: boolean;
  /** True on a poll answered anonymously. Anonymity can be turned on
   *  afterwards, never off — it only ever hides more. */
  anonymityLocked?: boolean;
  idPrefix?: string;
}

const Toggle = ({
  id,
  label,
  hint,
  checked,
  disabled,
  onCheckedChange,
}: {
  id: string;
  label: string;
  hint: string;
  checked: boolean;
  disabled?: boolean;
  onCheckedChange: (next: boolean) => void;
}) => (
  <div className="flex items-start justify-between gap-3">
    <div className="min-w-0">
      <Label htmlFor={id} className="text-sm">
        {label}
      </Label>
      <p className="text-muted-foreground text-xs">{hint}</p>
    </div>
    <Switch
      id={id}
      checked={checked}
      disabled={disabled}
      onCheckedChange={onCheckedChange}
      className="mt-0.5 shrink-0"
    />
  </div>
);

/**
 * Writing the question a notice asks.
 *
 * Controlled, and used in both places a poll is written — the composer, where
 * the notice and its question are one submission, and the notice's own page,
 * where the question is added or reworded afterwards. Neither owns the rules;
 * they live in `isPollDraftValid` beside the draft it validates.
 *
 * The two locks are the honest half of "edit an answered poll": most of it
 * stays editable, and this says which parts do not rather than refusing the
 * whole edit.
 */
export const PollEditor = ({
  value,
  onChange,
  onRemove,
  choicesLocked = false,
  anonymityLocked = false,
  idPrefix = "poll",
}: PollEditorProps) => {
  const { t } = useTranslation(["posts", "common"]);

  const setOption = (index: number, text: string) =>
    onChange({
      ...value,
      options: value.options.map((option, at) => (at === index ? text : option)),
    });

  return (
    <div className="space-y-4 rounded-md border bg-card p-3">
      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-question`}>{t("poll.question")}</Label>
        <Input
          id={`${idPrefix}-question`}
          value={value.question}
          maxLength={255}
          placeholder={t("poll.questionPlaceholder")}
          onChange={(event) => onChange({ ...value, question: event.target.value })}
        />
        <p className="text-muted-foreground text-xs">{t("poll.questionHint")}</p>
      </div>

      <fieldset className="space-y-2" disabled={choicesLocked}>
        <legend className="pb-2 font-medium text-sm">{t("poll.choices")}</legend>
        {value.options.map((option, index) => (
          <div
            // The rows are positional — there is nothing else to key them by
            // until they are saved, and a row's identity here IS its place in
            // the list.
            // biome-ignore lint/suspicious/noArrayIndexKey: position is the identity
            key={index}
            className="flex items-center gap-2"
          >
            <Input
              value={option}
              maxLength={MAX_POLL_OPTION_CHARS}
              aria-label={t("poll.choiceNumber", { number: index + 1 })}
              placeholder={t("poll.choicePlaceholder", { number: index + 1 })}
              onChange={(event) => setOption(index, event.target.value)}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="shrink-0"
              // Never below the floor: removing the second-to-last row would
              // leave a poll that cannot be saved and no way back but retyping.
              disabled={value.options.length <= MIN_POLL_OPTIONS}
              aria-label={t("poll.removeChoice", { number: index + 1 })}
              onClick={() =>
                onChange({
                  ...value,
                  options: value.options.filter((_, at) => at !== index),
                })
              }
            >
              <X className="size-4" aria-hidden />
            </Button>
          </div>
        ))}
        {value.options.length < MAX_POLL_OPTIONS && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onChange({ ...value, options: [...value.options, ""] })}
          >
            <Plus className="size-4" aria-hidden />
            {t("poll.addChoice")}
          </Button>
        )}
        {choicesLocked && (
          <p className="text-muted-foreground text-xs">{t("poll.choicesLocked")}</p>
        )}
      </fieldset>

      <div className="space-y-3">
        <Toggle
          id={`${idPrefix}-multiple`}
          label={t("poll.allowsMultiple")}
          hint={t("poll.allowsMultipleHint")}
          checked={value.allowsMultiple}
          disabled={choicesLocked}
          onCheckedChange={(next) => onChange({ ...value, allowsMultiple: next })}
        />
        <Toggle
          id={`${idPrefix}-hide-results`}
          label={t("poll.hideResults")}
          hint={t("poll.hideResultsHint")}
          checked={value.hideResults}
          onCheckedChange={(next) => onChange({ ...value, hideResults: next })}
        />
        <Toggle
          id={`${idPrefix}-anonymous`}
          label={t("poll.isAnonymous")}
          hint={anonymityLocked ? t("poll.anonymityLocked") : t("poll.isAnonymousHint")}
          checked={value.isAnonymous}
          disabled={anonymityLocked}
          onCheckedChange={(next) => onChange({ ...value, isAnonymous: next })}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-closes`}>{t("poll.closesAt")}</Label>
        <DateTimePicker
          id={`${idPrefix}-closes`}
          includeTime
          value={value.closesAt}
          placeholder={t("poll.closesAtPlaceholder")}
          onChange={(next) => onChange({ ...value, closesAt: next })}
        />
        <p className="text-muted-foreground text-xs">{t("poll.closesAtHint")}</p>
      </div>

      {onRemove && (
        <Button type="button" variant="ghost" size="sm" onClick={onRemove}>
          {t("poll.remove")}
        </Button>
      )}
    </div>
  );
};
