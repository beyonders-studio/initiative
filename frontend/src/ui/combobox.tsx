import { Check, ChevronsUpDown, Loader2, type LucideIcon, Plus } from "lucide-react";
import {
  isValidElement,
  type ReactElement,
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { useFieldControl } from "@/ui/field";
import { fieldClass } from "@/ui/input";
import { commandFilter } from "@/ui/lib/fuzzyMatch";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";
import { cn } from "@/ui/lib/utils";

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
   *  of thing — or, given as an element, a picture of the row's own: a
   *  person's avatar, a tag's colour. */
  icon?: LucideIcon | ReactElement;
  /** Muted text after the label — what kind of thing this row is. */
  hint?: string;
  /**
   * Muted text on a second line — where this row lives. A name is often not
   * enough to tell two rows apart, and unlike {@link hint} this can be long,
   * so it gets a line of its own instead of competing with the label for the
   * one they would otherwise share. A search here matches it too, below the
   * label.
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
  /** Opens and closes the popover from outside, to close it once a form in
   *  `children` is done. Without it the popover opens and closes itself. */
  open?: boolean;
  /** Called when the popover opens/closes — gate the query's `enabled` on it. */
  onOpenChange?: (open: boolean) => void;
  /**
   * Offers what was typed as a choice when no item is named it, labelled with
   * what this returns, e.g. `Use "{{value}}"`. With `onCreate` it is asked
   * with nothing typed as well: return "" to offer nothing then, or a label to
   * offer making a new item from scratch. Not named for `use`: that prefix
   * reads as a hook to the linter, and it is a label.
   */
  typedLabel?: (typed: string) => string;
  /** Makes a new item of what was typed when its offer is chosen, in place of
   *  choosing it. The search is cleared once it is done, since what was typed
   *  is taken; a promise that rejects keeps it, to try again. */
  onCreate?: (typed: string) => unknown;
  /** Opens the popover in place of the field: a button of the caller's own,
   *  which names itself. `id`, `aria-label`, `placeholder` and `className`
   *  are the field's, and go unused beside it. */
  trigger?: ReactElement;
  /** The trigger's edge the popover lines up with: "end" for one at the end
   *  of a row. */
  align?: "start" | "end";
  /** Shown in the popover in place of the search and the list while given: a
   *  form that makes a new item, opened from `onCreate`. */
  children?: ReactNode;
  loading?: boolean;
  loadingLabel?: string;
  placeholder?: string;
  searchPlaceholder?: string;
  /** Shown when nothing is listed; with `multiple` searched here, in place of
   *  the field when there is nothing to choose. */
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
      /** Picks several, with select-all and clear where the list is searched
       *  here; the popover stays open. */
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
    onCreate,
    trigger,
    align = "start",
    children,
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
  const field = useFieldControl({ id });
  const [ownOpen, setOwnOpen] = useState(false);
  const open = !disabled && (props.open ?? ownOpen);
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
            .map((item) => ({
              item,
              score: commandFilter(item.label, query, item.sublabel ? [item.sublabel] : []),
            }))
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
  // Searched on the server, `items` is one page of matches, so "all" of it is
  // not everything, and a lone choice may be missing from it.
  if (props.multiple && chosen.length > 0) {
    chosenLabel =
      !searchedOnServer && chosen.length === items.length
        ? t("multiSelect.allSelected")
        : (chosen.length === 1 && firstChosen?.label) ||
          t("multiSelect.countSelected", { count: chosen.length });
  }

  const typed = query.trim();
  const typedOffer =
    (typed !== "" || onCreate !== undefined) &&
    !items.some((item) => item.label.toLowerCase() === typed.toLowerCase()) &&
    typedLabel?.(typed);

  const handleOpenChange = (nextOpen: boolean) => {
    setOwnOpen(nextOpen);
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

  const takeTyped = () => {
    if (!onCreate) return choose(typed);
    Promise.resolve(onCreate(typed)).then(
      () => setQuery(""),
      () => {}
    );
  };

  // Searched here, with nothing loading and nothing to type, an empty list of
  // several has nothing to choose, which is said in place of the field.
  if (props.multiple && items.length === 0 && !searchedOnServer && !typedLabel && !loading) {
    return (
      <p className="text-muted-foreground text-sm">{emptyMessage ?? t("multiSelect.empty")}</p>
    );
  }

  const popover = (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        {trigger ?? (
          <button
            type="button"
            role="combobox"
            aria-expanded={open}
            aria-label={ariaLabel}
            {...field}
            className={cn(
              fieldClass,
              "items-center justify-between gap-2",
              !chosenLabel && "text-muted-foreground"
            )}
            disabled={disabled}
          >
            <span className="truncate">
              {chosenLabel || placeholder || t("combobox.placeholder")}
            </span>
            <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
          </button>
        )}
      </PopoverTrigger>
      <PopoverContent className="w-[320px] min-w-(--radix-popover-trigger-width) p-0" align={align}>
        {children || (
          <Command shouldFilter={false}>
            <CommandInput
              placeholder={searchPlaceholder ?? t("combobox.search")}
              value={query}
              onValueChange={setQuery}
            />
            <CommandList>
              {/* Offered whenever what was typed is not itself an item —
                  `role` has to be choosable while `roles` is listed. */}
              {typedOffer ? (
                <CommandGroup>
                  <CommandItem
                    value={`__typed__${typed}`}
                    onSelect={takeTyped}
                    className="text-muted-foreground"
                  >
                    {onCreate ? (
                      <Plus className="h-4 w-4" />
                    ) : (
                      <Check className="h-4 w-4 opacity-0" />
                    )}
                    {typedOffer}
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
                  {/* Searched here, a list of several is empty only when a
                      search found nothing, which `emptyMessage` doesn't
                      describe. */}
                  <CommandEmpty>
                    {((!props.multiple || searchedOnServer) && emptyMessage) ||
                      t("combobox.noResults")}
                  </CommandEmpty>
                  {props.multiple && !searchedOnServer && !query && items.length > 0 ? (
                    <>
                      <CommandGroup>
                        {/* Every item that can be chosen, added to what is
                            chosen already, listed or not. */}
                        <CommandItem
                          disabled={items.every(
                            (item) => item.disabled || chosen.includes(item.value)
                          )}
                          onSelect={() =>
                            props.onValueChange([
                              ...chosen,
                              ...items
                                .filter((item) => !item.disabled && !chosen.includes(item.value))
                                .map((item) => item.value),
                            ])
                          }
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
                            {isValidElement(item.icon) ? (
                              // As tall as the label's first line, so an
                              // avatar or a swatch sits level with it.
                              <span className="flex h-5 shrink-0 items-center">{item.icon}</span>
                            ) : item.icon ? (
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
        )}
      </PopoverContent>
    </Popover>
  );

  return trigger ? popover : <div className={cn("w-full", className)}>{popover}</div>;
};
