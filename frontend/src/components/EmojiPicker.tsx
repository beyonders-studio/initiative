/**
 * The "pick an icon" control — a button showing the current emoji that opens
 * the shared picker. Used wherever an entity carries an emoji of its own (a
 * project's icon today).
 *
 * The picker itself is `@/components/ui/emoji-picker`, so this control and the
 * reaction picker search the same dataset and look the same doing it.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  EmojiPicker as EmojiPickerBase,
  EmojiPickerContent,
  EmojiPickerFooter,
  EmojiPickerSearch,
} from "@/components/ui/emoji-picker";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

interface EmojiPickerProps {
  id?: string;
  value?: string | null;
  onChange: (emoji: string | null) => void;
  disabled?: boolean;
  placeholder?: string;
}

export const EmojiPicker = ({
  id,
  value,
  onChange,
  disabled = false,
  placeholder,
}: EmojiPickerProps) => {
  const { t } = useTranslation("ui");
  const [open, setOpen] = useState(false);

  return (
    <div className="flex w-full flex-col gap-1">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            id={id}
            variant="outline"
            className="w-full justify-start"
            disabled={disabled}
          >
            {value ? (
              <span className="text-xl leading-none">{value}</span>
            ) : (
              <span className="text-sm">{placeholder ?? t("emojiPicker.pick")}</span>
            )}
          </Button>
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
          <EmojiPickerBase
            className="h-[340px]"
            onEmojiSelect={({ emoji }) => {
              onChange(emoji);
              setOpen(false);
            }}
          >
            <EmojiPickerSearch />
            <EmojiPickerContent />
            <EmojiPickerFooter />
          </EmojiPickerBase>
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
