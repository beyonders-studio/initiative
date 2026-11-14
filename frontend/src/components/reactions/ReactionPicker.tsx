/**
 * The "add a reaction" control: an icon-only button opening a fixed row of
 * suggested emoji over the full picker.
 *
 * The suggested row comes from the server, so everyone sees the same
 * suggestions — the point of the thing. A per-browser "frequently used" row
 * would show each person a different set and defeat the shared vocabulary a
 * reaction bar is for.
 */

import { SmilePlus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useSuggestedReactions } from "@/hooks/useReactions";
import { Button } from "@/ui/button";
import {
  EmojiPicker,
  EmojiPickerContent,
  EmojiPickerFooter,
  EmojiPickerSearch,
} from "@/ui/emoji-picker";
import { cn } from "@/ui/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/ui/popover";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

interface ReactionPickerProps {
  onSelect: (emoji: string) => void;
  disabled?: boolean;
  /** Emoji the current user has already picked — shown pressed in the row. */
  mine?: ReadonlySet<string>;
  className?: string;
}

export const ReactionPicker = ({
  onSelect,
  disabled = false,
  mine,
  className,
}: ReactionPickerProps) => {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  // Only asked for once the picker is opened: a thread of fifty comments
  // should not make fifty requests to render fifty buttons.
  const { data: suggested = [] } = useSuggestedReactions({ enabled: open });

  const choose = (emoji: string) => {
    onSelect(emoji);
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={disabled}
                aria-label={t("reactions.add")}
                className={cn("h-7 w-7 p-0 text-muted-foreground", className)}
              >
                <SmilePlus className="h-4 w-4" aria-hidden="true" />
              </Button>
            </PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent>{t("reactions.add")}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
      {/* Capped at the room Radix measured, so an open mobile keyboard shrinks
          the emoji list instead of pushing the picker off screen. */}
      <PopoverContent
        className="flex w-fit flex-col overflow-hidden p-0"
        align="start"
        collisionPadding={8}
      >
        {suggested.length > 0 && (
          <div className="flex shrink-0 items-center gap-0.5 border-b p-1.5">
            {suggested.map((emoji) => (
              <button
                key={emoji}
                type="button"
                onClick={() => choose(emoji)}
                aria-label={emoji}
                aria-pressed={mine?.has(emoji) ?? false}
                className={cn(
                  "flex size-8 items-center justify-center rounded-sm text-lg hover:bg-accent",
                  mine?.has(emoji) && "bg-accent ring-1 ring-primary/40"
                )}
              >
                {emoji}
              </button>
            ))}
          </div>
        )}
        <EmojiPicker className="h-[320px]" onEmojiSelect={({ emoji }) => choose(emoji)}>
          <EmojiPickerSearch />
          <EmojiPickerContent />
          <EmojiPickerFooter />
        </EmojiPicker>
      </PopoverContent>
    </Popover>
  );
};
