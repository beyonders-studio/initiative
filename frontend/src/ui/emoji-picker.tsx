/**
 * shadcn-styled wrapper around frimousse's emoji picker primitives.
 *
 * Two things differ from the upstream registry component:
 *
 * - **The dataset comes from where the host says** (`emojibaseUrl`). Initiative
 *   serves its own, never a public CDN — a self-hosted install may have no
 *   internet at all.
 * - **Its strings and locale come from i18next**, so the picker searches and
 *   labels in the language the rest of the app is in.
 */

import {
  type EmojiPickerListCategoryHeaderProps,
  type EmojiPickerListEmojiProps,
  type EmojiPickerListRowProps,
  EmojiPicker as EmojiPickerPrimitive,
} from "frimousse";
import { LoaderIcon, SearchIcon } from "lucide-react";
import type * as React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { useFieldControl } from "@/ui/field";
import { host } from "@/ui/host";
import { fieldClass } from "@/ui/input";
import { cn } from "@/ui/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/ui/popover";

/** Locales the emoji dataset is shipped for; anything else falls back to English. */
const SUPPORTED_LOCALES = ["en", "de", "es", "fr"] as const;
type EmojiLocale = (typeof SUPPORTED_LOCALES)[number];

const emojiLocale = (language: string): EmojiLocale => {
  const base = language.split("-")[0] as EmojiLocale;
  return SUPPORTED_LOCALES.includes(base) ? base : "en";
};

function EmojiPicker({
  className,
  ...props
}: React.ComponentProps<typeof EmojiPickerPrimitive.Root>) {
  const { i18n } = useTranslation();
  return (
    <EmojiPickerPrimitive.Root
      locale={emojiLocale(i18n.language)}
      emojibaseUrl={host.emojibaseUrl}
      className={cn(
        "isolate flex h-full min-h-0 w-fit flex-col overflow-hidden rounded-md bg-popover text-popover-foreground",
        className
      )}
      data-slot="emoji-picker"
      {...props}
    />
  );
}

function EmojiPickerSearch({
  className,
  placeholder,
  ...props
}: React.ComponentProps<typeof EmojiPickerPrimitive.Search>) {
  const { t } = useTranslation("ui");
  return (
    <div
      className={cn("flex h-9 shrink-0 items-center gap-2 border-b px-3", className)}
      data-slot="emoji-picker-search-wrapper"
    >
      <SearchIcon className="size-4 shrink-0 opacity-50" />
      <EmojiPickerPrimitive.Search
        className="flex h-10 w-full rounded-md bg-transparent py-3 text-sm outline-hidden placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50"
        data-slot="emoji-picker-search"
        placeholder={placeholder ?? t("emojiPicker.searchPlaceholder")}
        {...props}
      />
    </div>
  );
}

function EmojiPickerRow({ children, ...props }: EmojiPickerListRowProps) {
  return (
    <div {...props} className="scroll-my-1 px-1" data-slot="emoji-picker-row">
      {children}
    </div>
  );
}

function EmojiPickerEmoji({ emoji, className, ...props }: EmojiPickerListEmojiProps) {
  return (
    <button
      {...props}
      className={cn(
        "flex size-7 items-center justify-center rounded-sm text-base data-active:bg-accent",
        className
      )}
      data-slot="emoji-picker-emoji"
    >
      {emoji.emoji}
    </button>
  );
}

function EmojiPickerCategoryHeader({ category, ...props }: EmojiPickerListCategoryHeaderProps) {
  return (
    <div
      {...props}
      className="bg-popover px-3 pt-3.5 pb-2 text-muted-foreground text-xs leading-none"
      data-slot="emoji-picker-category-header"
    >
      {category.label}
    </div>
  );
}

function EmojiPickerContent({
  className,
  ...props
}: React.ComponentProps<typeof EmojiPickerPrimitive.Viewport>) {
  const { t } = useTranslation("ui");
  return (
    <EmojiPickerPrimitive.Viewport
      className={cn("relative min-h-0 flex-1 outline-hidden", className)}
      data-slot="emoji-picker-viewport"
      {...props}
    >
      <EmojiPickerPrimitive.Loading
        className="absolute inset-0 flex items-center justify-center text-muted-foreground"
        data-slot="emoji-picker-loading"
      >
        <LoaderIcon className="size-4 animate-spin" />
      </EmojiPickerPrimitive.Loading>
      <EmojiPickerPrimitive.Empty
        className="absolute inset-0 flex items-center justify-center text-muted-foreground text-sm"
        data-slot="emoji-picker-empty"
      >
        {t("emojiPicker.empty")}
      </EmojiPickerPrimitive.Empty>
      <EmojiPickerPrimitive.List
        className="select-none pb-1"
        components={{
          Row: EmojiPickerRow,
          Emoji: EmojiPickerEmoji,
          CategoryHeader: EmojiPickerCategoryHeader,
        }}
        data-slot="emoji-picker-list"
      />
    </EmojiPickerPrimitive.Viewport>
  );
}

function EmojiPickerFooter({ className, ...props }: React.ComponentProps<"div">) {
  const { t } = useTranslation("ui");
  return (
    <div
      className={cn(
        "flex w-full min-w-0 max-w-(--frimousse-viewport-width) shrink-0 items-center gap-1 border-t p-2",
        className
      )}
      data-slot="emoji-picker-footer"
      {...props}
    >
      <EmojiPickerPrimitive.ActiveEmoji>
        {({ emoji }) =>
          emoji ? (
            <>
              <div className="flex size-7 flex-none items-center justify-center text-lg">
                {emoji.emoji}
              </div>
              <span className="truncate text-secondary-foreground text-xs">{emoji.label}</span>
            </>
          ) : (
            <span className="ml-1.5 flex h-7 items-center truncate text-muted-foreground text-xs">
              {t("emojiPicker.prompt")}
            </span>
          )
        }
      </EmojiPickerPrimitive.ActiveEmoji>
    </div>
  );
}

/**
 * A field holding one emoji: a button showing it, which opens the picker
 * above, and a way to clear it. Used wherever something carries an emoji of
 * its own, as a project's icon does, so it and the reaction picker search the
 * same dataset and look the same doing it.
 */
interface EmojiFieldProps {
  id?: string;
  value?: string | null;
  onChange: (emoji: string | null) => void;
  disabled?: boolean;
  placeholder?: string;
}

const EmojiField = ({ id, value, onChange, disabled = false, placeholder }: EmojiFieldProps) => {
  const { t } = useTranslation("ui");
  const field = useFieldControl({ id });
  const [open, setOpen] = useState(false);

  return (
    <div className="flex w-full flex-col gap-1">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            {...field}
            className={cn(fieldClass, "items-center")}
            disabled={disabled}
          >
            {value ? (
              <span className="text-xl leading-none">{value}</span>
            ) : (
              <span className="text-muted-foreground">{placeholder ?? t("emojiPicker.pick")}</span>
            )}
          </button>
        </PopoverTrigger>
        {/*
          The popover is capped at the room Radix measured for it rather than
          at the picker's own 340px: on a phone the keyboard takes most of the
          screen while the search field is focused, and a fixed height would
          run off the top edge. The picker is a flex child so the emoji list
          gives way first — search and footer stay where they are.
        */}
        <PopoverContent
          className="flex w-fit flex-col overflow-hidden p-0"
          align="start"
          collisionPadding={8}
        >
          <EmojiPicker
            className="h-[340px]"
            onEmojiSelect={({ emoji }) => {
              onChange(emoji);
              setOpen(false);
            }}
          >
            <EmojiPickerSearch />
            <EmojiPickerContent />
            <EmojiPickerFooter />
          </EmojiPicker>
        </PopoverContent>
      </Popover>
      {value ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="self-start px-2"
          onClick={() => onChange(null)}
          disabled={disabled}
        >
          {t("clear")}
        </Button>
      ) : null}
    </div>
  );
};

export { EmojiField, EmojiPicker, EmojiPickerContent, EmojiPickerFooter, EmojiPickerSearch };
