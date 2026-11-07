import { Check, ChevronsUpDown, type LucideIcon } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

import { Button } from "./button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem } from "./command";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";

export interface SearchableComboboxItem {
  value: string;
  label: string;
  /**
   * Drawn before the label, for a list whose rows are not all the same sort of
   * thing. Only {@link AsyncCombobox} draws these two: it is the variant backed
   * by a server typeahead, which is what a list of mixed kinds is served from.
   */
  icon?: LucideIcon;
  /** Muted text after the label — what kind of thing this row is. */
  hint?: string;
  /**
   * Muted text on a second line — where this row lives. A name is often not
   * enough to tell two rows apart, and unlike {@link hint} this can be long,
   * so it gets a line of its own instead of competing with the label for the
   * one they would otherwise share. Only {@link AsyncCombobox} draws it.
   */
  sublabel?: string;
  /** Listed but not choosable — say why in {@link hint}. */
  disabled?: boolean;
}

export interface SearchableComboboxProps {
  items: SearchableComboboxItem[];
  value?: string | null;
  onValueChange?: (value: string) => void;
  placeholder?: string;
  emptyMessage?: string;
  className?: string;
  buttonClassName?: string;
  disabled?: boolean;
  "aria-label"?: string;
}

export const SearchableCombobox = ({
  items,
  value,
  onValueChange,
  placeholder = "Select an option",
  emptyMessage = "No results found.",
  className,
  buttonClassName,
  disabled = false,
  "aria-label": ariaLabel,
}: SearchableComboboxProps) => {
  const [open, setOpen] = useState(false);
  const [internalValue, setInternalValue] = useState(value ?? "");

  const selectedValue = value === undefined ? internalValue : (value ?? "");
  const selectedItem = items.find(
    (item) => item.value.toLowerCase() === selectedValue.toLowerCase()
  );

  const handleSelect = (currentValue: string) => {
    if (disabled) {
      return;
    }
    setInternalValue(currentValue);
    onValueChange?.(currentValue);
    setOpen(false);
  };

  return (
    <div className={cn("w-full", className)}>
      <Popover
        open={disabled ? false : open}
        onOpenChange={(nextOpen) => !disabled && setOpen(nextOpen)}
      >
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={!disabled && open}
            aria-label={ariaLabel}
            className={cn("w-full justify-between", buttonClassName)}
            disabled={disabled}
          >
            {selectedItem?.label ?? placeholder}
            <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[320px] p-0">
          <Command>
            <CommandInput placeholder="Search..." disabled={disabled} />
            <CommandEmpty>{emptyMessage}</CommandEmpty>
            <CommandGroup className="max-h-64 overflow-y-auto">
              {items.map((item) => (
                <CommandItem
                  key={item.value}
                  value={item.label}
                  disabled={item.disabled}
                  onSelect={() => handleSelect(item.value)}
                >
                  <Check
                    className={cn(
                      "h-4 w-4",
                      item.value === selectedValue ? "opacity-100" : "opacity-0"
                    )}
                  />
                  {item.label}
                </CommandItem>
              ))}
            </CommandGroup>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
};
