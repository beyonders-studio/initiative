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
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import { host } from "@/ui/host";

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

export { EmojiPicker, EmojiPickerContent, EmojiPickerFooter, EmojiPickerSearch };
