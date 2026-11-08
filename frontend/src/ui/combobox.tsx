import { Check, ChevronsUpDown, Loader2, type LucideIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { commandFilter } from "@/ui/lib/fuzzyMatch";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";
import { cn } from "@/ui/lib/utils";

import { Button } from "./button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "./command";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";

export interface ComboboxItem {
  value: string;
  label: string;
  /** Drawn before the label, for a list whose rows are not all the same sort
   *  of thing. */
  icon?: LucideIcon;
  /** Muted text after the label — what kind of thing this row is. */
  hint?: string;
  /**
   * Muted text on a second line — where this row lives. A name is often not
   * enough to tell two rows apart, and unlike {@link hint} this can be long,
   * so it gets a line of its own instead of competing with the label for the
   * one they would otherwise share.
   */
  sublabel?: string;
  /** Listed but not choosable — say why in {@link hint}. */
  disabled?: boolean;
  /** Heading to list this item under. Ungrouped items come first, then each
   *  group in the order it first appears. */
  group?: string;
}

export type ComboboxProps = {
  items: ComboboxItem[];
  /**
   * Hands the search to the server: called with the debounced search text,
   * and with "" on mount and when the popover closes. Drive the query from
   * this — not from every keystroke — and pass back what matched as `items`,
   * which are then listed as given. Without it, `items` is the whole list and
   * is searched here.
   */
  onSearchChange?: (query: string) => void;
  debounceMs?: number;
  /** Called when the popover opens/closes — gate the query's `enabled` on it. */
  onOpenChange?: (open: boolean) => void;
  /** Offers what was typed as a choice when no item is named it, e.g.
   *  `Use "{{value}}"`. Not named for `use`: that prefix reads as a hook to
   *  the linter, and it is a label. */
  typedLabel?: (typed: string) => string;
  loading?: boolean;
  loadingLabel?: string;
  placeholder?: string;
  searchPlaceholder?: string;
  /** Shown when nothing is listed; with `multiple`, in place of the field
   *  when there is nothing to choose. */
  emptyMessage?: string;
  /** Ties the trigger to a `<Label htmlFor>`. A `combobox` takes no accessible
   *  name from its own contents, so without this or `aria-label` the control
   *  is unnamed. */
  id?: string;
  className?: string;
  disabled?: boolean;
  "aria-label"?: string;
} & (
  | {
      multiple?: false;
      value?: string | null;
      onValueChange?: (value: string) => void;
      /**
       * Label for the current `value`. Server search only returns matches for
       * the live query, so the selected item is often absent from `items`;
       * the caller remembers its label.
       */
      selectedLabel?: string | null;
    }
  | {
      /** Picks several, with select-all and clear; the popover stays open. */
      multiple: true;
      value: string[];
      onValueChange: (values: string[]) => void;
    }
);

/**
 * A field that picks one item, or several with `multiple`, from a list it
 * searches.
 *
 * With `onSearchChange` the server decides what matches, which keeps the
 * request proportional to what the user is looking for in a collection that
 * can run to tens of thousands of rows. Without it the list is searched here,
 * forgiving typos and ranking an exact name first.
 */
export const Combobox = (props: ComboboxProps) => {
  const {
    items,
    onSearchChange,
    debounceMs = 250,
    onOpenChange,
    typedLabel,
    loading = false,
    loadingLabel,
    placeholder,
    searchPlaceholder,
    emptyMessage,
    id,
    className,
    disabled = false,
    "aria-label": ariaLabel,
  } = props;
  const { t } = useTranslation("ui");
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebouncedValue(query, debounceMs);

  // Held in a ref so an inline (unmemoized) callback prop doesn't re-fire the
  // search on every render of the parent.
  const onSearchChangeRef = useRef(onSearchChange);
  onSearchChangeRef.current = onSearchChange;

  useEffect(() => {
    onSearchChangeRef.current?.(debouncedQuery);
  }, [debouncedQuery]);

  // Ranked here rather than by cmdk, whose filter reads an item's cmdk value:
  // that value has to be unique, and labels need not be.
  const searchedOnServer = onSearchChange !== undefined;
  const groups = useMemo(() => {
    const shown =
      searchedOnServer || !query
        ? items
        : items
            .map((item) => ({ item, score: commandFilter(item.label, query) }))
            .filter(({ score }) => score > 0)
            .sort((a, b) => b.score - a.score)
            .map(({ item }) => item);
    const byHeading = new Map<string, ComboboxItem[]>([["", []]]);
    for (const item of shown) {
      const group = byHeading.get(item.group ?? "");
      if (group) group.push(item);
      else byHeading.set(item.group ?? "", [item]);
    }
    return [...byHeading];
  }, [items, query, searchedOnServer]);

  const chosen = props.multiple ? props.value : props.value == null ? [] : [props.value];
  const firstChosen = items.find((item) => item.value === chosen[0]);
  let chosenLabel = props.multiple ? undefined : props.selectedLabel || firstChosen?.label;
  if (props.multiple && chosen.length > 0) {
    chosenLabel =
      chosen.length === items.length
        ? t("multiSelect.allSelected")
        : chosen.length === 1
          ? firstChosen?.label
          : t("multiSelect.countSelected", { count: chosen.length });
  }

  const typed = query.toLowerCase();
  const offerTyped =
    typedLabel !== undefined &&
    query !== "" &&
    !items.some((item) => item.label.toLowerCase() === typed);

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    onOpenChange?.(nextOpen);
    if (!nextOpen) setQuery("");
  };

  const choose = (value: string) => {
    if (!props.multiple) {
      props.onValueChange?.(value);
      handleOpenChange(false);
    } else if (chosen.includes(value)) {
      props.onValueChange(chosen.filter((each) => each !== value));
    } else {
      props.onValueChange([...chosen, value]);
    }
  };

  if (props.multiple && items.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">{emptyMessage ?? t("multiSelect.empty")}</p>
    );
  }

  return (
    <div className={cn("w-full", className)}>
      <Popover open={!disabled && open} onOpenChange={handleOpenChange}>
        <PopoverTrigger asChild>
          <Button
            id={id}
            variant="outline"
            role="combobox"
            aria-expanded={!disabled && open}
            aria-label={ariaLabel}
            className={cn(
              "w-full justify-between font-normal",
              !chosenLabel && "text-muted-foreground"
            )}
            disabled={disabled}
          >
            <span className="truncate">
              {chosenLabel || placeholder || t("combobox.placeholder")}
            </span>
            <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          className="w-[320px] min-w-(--radix-popover-trigger-width) p-0"
          align="start"
        >
          <Command shouldFilter={false}>
            <CommandInput
              placeholder={searchPlaceholder ?? t("combobox.search")}
              value={query}
              onValueChange={setQuery}
            />
            <CommandList>
              {/* Offered whenever what was typed is not itself an item —
                  `role` has to be choosable while `roles` is listed. */}
              {offerTyped ? (
                <CommandGroup>
                  <CommandItem
                    value={`__typed__${query}`}
                    onSelect={() => choose(query)}
                    className="text-muted-foreground"
                  >
                    <Check className="h-4 w-4 opacity-0" />
                    {typedLabel(query)}
                  </CommandItem>
                </CommandGroup>
              ) : null}
              {loading ? (
                <div className="flex items-center justify-center gap-2 py-6 text-muted-foreground text-sm">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {loadingLabel ?? t("loading")}
                </div>
              ) : (
                <>
                  {/* With `multiple`, the list is empty only when a search
                      found nothing, which `emptyMessage` doesn't describe. */}
                  <CommandEmpty>
                    {(!props.multiple && emptyMessage) || t("combobox.noResults")}
                  </CommandEmpty>
                  {props.multiple && !query ? (
                    <>
                      <CommandGroup>
                        <CommandItem
                          disabled={chosen.length === items.length}
                          onSelect={() => props.onValueChange(items.map((item) => item.value))}
                        >
                          {t("selectAll")}
                        </CommandItem>
                        <CommandItem
                          disabled={chosen.length === 0}
                          onSelect={() => props.onValueChange([])}
                        >
                          {t("multiSelect.clearAll")}
                        </CommandItem>
                      </CommandGroup>
                      <CommandSeparator />
                    </>
                  ) : null}
                  {groups.map(([heading, group]) =>
                    group.length > 0 ? (
                      <CommandGroup key={heading} heading={heading || undefined}>
                        {group.map((item) => (
                          <CommandItem
                            key={item.value}
                            value={item.value}
                            // Top-aligned rather than centred: a row with a
                            // second line is taller than the tick and the icon
                            // beside it.
                            className="items-start"
                            disabled={item.disabled}
                            aria-checked={chosen.includes(item.value)}
                            onSelect={() => choose(item.value)}
                          >
                            <Check
                              className={cn(
                                "mt-0.5 h-4 w-4 shrink-0",
                                chosen.includes(item.value) ? "opacity-100" : "opacity-0"
                              )}
                            />
                            {item.icon ? (
                              <item.icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                            ) : null}
                            <span className="min-w-0 flex-1">
                              <span className="block truncate">{item.label}</span>
                              {/* Where the row lives. Two things of the same
                                  name are told apart by this line and nothing
                                  else, so it is drawn under the name rather
                                  than squeezed beside it. */}
                              {item.sublabel ? (
                                <span className="block truncate text-muted-foreground text-xs">
                                  {item.sublabel}
                                </span>
                              ) : null}
                            </span>
                            {item.hint ? (
                              <span className="mt-0.5 shrink-0 pl-2 text-muted-foreground text-xs">
                                {item.hint}
                              </span>
                            ) : null}
                          </CommandItem>
                        ))}
                      </CommandGroup>
                    ) : null
                  )}
                </>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
};
