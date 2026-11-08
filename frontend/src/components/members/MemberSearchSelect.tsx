import { Check, ChevronDown, ChevronsUpDown, Loader2, Users, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserSummary } from "@/api/generated/initiativeAPI.schemas";
import { type MemberSearchScope, USER_ID_LOOKUP_MAX, useMemberSearch } from "@/hooks/useUsers";
import {
  getAvatarSrc,
  getInitialsForUser,
  getUserDisplayName,
  hasDisplayName,
} from "@/lib/userDisplay";
import { Avatar, AvatarFallback, AvatarImage } from "@/ui/avatar";
import { Button } from "@/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/ui/command";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";
import { cn } from "@/ui/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/ui/popover";

/** The slim user shape these pickers render (the search endpoints' `UserSummary`). */
export type MemberSummary = Pick<
  UserSummary,
  "id" | "username" | "discriminator" | "display_name" | "avatar_url" | "status" | "community_role"
>;

/** A member we can render from partial info — a full {@link MemberSummary} from
 *  search, or just an `{ id }` fallback for a selected user we haven't resolved
 *  yet. The display/avatar helpers tolerate the missing fields. */
export type MemberLike = { id: number } & Partial<MemberSummary>;

/** Accumulate display info for users we've seen — from the caller-provided
 *  already-selected set, every search page, and the id lookup below — so a
 *  selected chip keeps its name/avatar even after the query changes and the
 *  row leaves the results.
 *
 *  A selection can also arrive as bare ids with no display info at all: a
 *  filter restored from storage, a stored user-reference property, a page
 *  opened straight onto an existing selection. Those ids are resolved against
 *  the same scoped roster the dropdown searches, so the trigger names them
 *  instead of falling back to "User #<id>". Ids are resolved a lookup page at
 *  a time, so any number of them is named in the end. */
export const useSeenMembers = (
  scope: MemberSearchScope,
  selectedIds: number[],
  selectedUsers: MemberLike[] | undefined,
  results: MemberSummary[]
) => {
  const [seen, setSeen] = useState<Map<number, MemberLike>>(() => new Map());

  const unresolvedIds = useMemo(() => {
    const known = new Map<number, MemberLike>(seen);
    for (const user of [...(selectedUsers ?? []), ...results]) known.set(user.id, user);
    // Sorted so the lookup's query key doesn't churn with selection order.
    return selectedIds.filter((id) => !hasDisplayName(known.get(id))).sort((a, b) => a - b);
  }, [seen, selectedIds, selectedUsers, results]);

  const lookup = useMemberSearch(scope, {
    userIds: unresolvedIds,
    pageSize: USER_ID_LOOKUP_MAX,
    enabled: unresolvedIds.length > 0,
  });
  const resolved = useMemo<MemberSummary[]>(() => lookup.data?.items ?? [], [lookup.data]);

  useEffect(() => {
    setSeen((prev) => {
      const next = new Map(prev);
      let changed = false;
      // Add an id we haven't seen, and upgrade a placeholder we couldn't name
      // once a named record arrives. Every other case must be a no-op — the
      // update has to be idempotent, or a fresh array identity on each render
      // would loop (setState → render → effect → setState).
      for (const user of [...(selectedUsers ?? []), ...results, ...resolved]) {
        const current = next.get(user.id);
        if (current && (hasDisplayName(current) || !hasDisplayName(user))) continue;
        next.set(user.id, user);
        changed = true;
      }
      return changed ? next : prev;
    });
  }, [selectedUsers, results, resolved]);

  return seen;
};

/** A person's picture, or their initials in their own colour. */
export const MemberAvatar = ({ user, className }: { user: MemberLike; className?: string }) => {
  const src = getAvatarSrc(user);
  const label = getUserDisplayName(user);
  return (
    <Avatar className={cn("h-6 w-6 border text-3xs", className)}>
      {src ? <AvatarImage src={src} alt={label} /> : null}
      <AvatarFallback userId={user.id}>{getInitialsForUser(user)}</AvatarFallback>
    </Avatar>
  );
};

// ── Multi-select (assignees, linked members) ─────────────────────────────────

/**
 * A non-person entry listed above the people.
 *
 * Some assignee filters don't name a user at all: "me" is whoever is asking,
 * "unassigned" is nobody. Both are resolved server-side per request, which is
 * what lets a saved filter — and a link to it — mean the same thing for
 * everyone. They belong in the same control as the people, since they answer
 * the same question, but they are not ids and can't go through `selectedIds`.
 */
export type MemberToken = {
  value: string;
  label: string;
  selected: boolean;
  onToggle: (selected: boolean) => void;
};

interface MemberMultiSelectProps {
  /** Which RLS-scoped roster to search (community / initiative / project). */
  scope: MemberSearchScope;
  /** Ties the trigger to a `<Label htmlFor>`. A `combobox` takes no accessible
   *  name from its own contents, so without this the control is unnamed. */
  id?: string;
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  /** Entries listed above the people — see {@link MemberToken}. */
  tokens?: readonly MemberToken[];
  /** Display info for already-selected users (e.g. a task's `assignees`) so
   *  chips render before/without a search. */
  selectedUsers?: MemberLike[];
  /** Floats the current user to the top of the results for quick self-assign. */
  currentUserId?: number;
  disabled?: boolean;
  placeholder?: string;
  emptyMessage?: string;
  className?: string;
  /**
   * "default" — full editor: avatar chips in the trigger + a "clear" button
   * below (assignee/member editing).
   * "filter" — compact `h-9` trigger matching the sibling filter dropdowns
   * (a summary label, no chips, no clear button).
   */
  variant?: "default" | "filter";
}

export const MemberMultiSelect = ({
  scope,
  id,
  selectedIds,
  onChange,
  tokens = [],
  selectedUsers,
  currentUserId,
  disabled = false,
  placeholder,
  emptyMessage,
  className,
  variant = "default",
}: MemberMultiSelectProps) => {
  const { t } = useTranslation(["projects", "common"]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 250);

  const searchResult = useMemberSearch(scope, { search: debounced, enabled: open });
  const results = useMemo<MemberSummary[]>(
    () => searchResult.data?.items ?? [],
    [searchResult.data]
  );
  const seen = useSeenMembers(scope, selectedIds, selectedUsers, results);

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const resolvedPlaceholder = placeholder ?? t("projects:assignee.searchPlaceholder");
  const resolvedEmpty = emptyMessage ?? t("projects:assignee.emptyMessage");

  // Always surface the currently-selected members, even when the active search
  // doesn't return them — otherwise a selection the server no longer matches
  // (a stale saved filter, or a member who lost access) could never be
  // de-selected from the dropdown. They render checked (resolved via `seen`,
  // falling back to "User #<id>") and toggling removes them. Then current user
  // first, then everyone else (results are already name-sorted).
  const orderedResults = useMemo<MemberLike[]>(() => {
    const resultIds = new Set(results.map((u) => u.id));
    const selectedNotInResults = selectedIds
      .filter((id) => !resultIds.has(id))
      .map((id): MemberLike => seen.get(id) ?? { id });
    const merged: MemberLike[] = [...selectedNotInResults, ...results];
    if (currentUserId == null) return merged;
    const mine = merged.filter((u) => u.id === currentUserId);
    const rest = merged.filter((u) => u.id !== currentUserId);
    return [...mine, ...rest];
  }, [results, selectedIds, seen, currentUserId]);

  const toggle = (id: number) => {
    if (!Number.isFinite(id)) return;
    if (selectedSet.has(id)) {
      onChange(selectedIds.filter((value) => value !== id));
    } else {
      onChange([...selectedIds, id]);
    }
  };

  const remove = (id: number) => onChange(selectedIds.filter((value) => value !== id));

  const handleOpenChange = (next: boolean) => {
    if (disabled) return;
    setOpen(next);
    if (!next) setQuery("");
  };

  // Compact summary for the filter variant: placeholder / the single name /
  // "N selected".
  const filterSummary = useMemo(() => {
    // Tokens count toward the summary: with only "Unassigned" on, a trigger
    // still reading "All assignees" would misdescribe the list.
    const chosenTokens = tokens.filter((token) => token.selected);
    const total = chosenTokens.length + selectedIds.length;
    if (total === 0) return resolvedPlaceholder;
    if (total === 1) {
      if (chosenTokens.length === 1) return chosenTokens[0].label;
      const only = seen.get(selectedIds[0]);
      return getUserDisplayName(only ?? { id: selectedIds[0] });
    }
    return t("common:countSelected", { count: total });
  }, [selectedIds, tokens, seen, resolvedPlaceholder, t]);

  return (
    <div className={cn(variant === "default" && "space-y-3", className)}>
      <Popover open={disabled ? false : open} onOpenChange={handleOpenChange}>
        <PopoverTrigger asChild>
          {variant === "filter" ? (
            <button
              type="button"
              id={id}
              role="combobox"
              aria-expanded={!disabled && open}
              disabled={disabled}
              className={cn(
                "flex h-9 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm ring-offset-background focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
                selectedIds.length === 0 &&
                  !tokens.some((token) => token.selected) &&
                  "text-muted-foreground"
              )}
            >
              <span className="truncate">{filterSummary}</span>
              <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
            </button>
          ) : (
            <Button
              variant="outline"
              role="combobox"
              aria-expanded={!disabled && open}
              disabled={disabled}
              className={cn(
                "h-auto min-h-10 w-full justify-start",
                selectedIds.length === 0 &&
                  !tokens.some((token) => token.selected) &&
                  "text-muted-foreground"
              )}
            >
              <Users className="h-4 w-4 shrink-0 opacity-50" />
              {selectedIds.length > 0 ? (
                <div className="flex flex-wrap gap-1">
                  {selectedIds.map((id) => {
                    const user = seen.get(id) ?? { id, display_name: null };
                    const label = getUserDisplayName(user);
                    return (
                      <span
                        key={id}
                        className="inline-flex max-w-full items-center gap-1 rounded-md bg-secondary py-0.5 pr-1.5 pl-1 font-medium text-secondary-foreground text-xs"
                      >
                        <MemberAvatar user={user} className="h-4 w-4 text-3xs" />
                        <span className="truncate">{label}</span>
                        <button
                          type="button"
                          className="rounded-sm hover:opacity-70 focus:outline-none"
                          aria-label={t("projects:assignee.removeAssignee", { name: label })}
                          onClick={(event) => {
                            event.stopPropagation();
                            event.preventDefault();
                            if (!disabled) remove(id);
                          }}
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    );
                  })}
                </div>
              ) : (
                <span>{resolvedPlaceholder}</span>
              )}
            </Button>
          )}
        </PopoverTrigger>
        <PopoverContent className="w-72 p-0" align="start">
          {/* Server-side search — never re-filter client-side. */}
          <Command shouldFilter={false}>
            <CommandInput
              placeholder={resolvedPlaceholder}
              value={query}
              onValueChange={setQuery}
            />
            <CommandList>
              {searchResult.isFetching && results.length === 0 ? (
                <div className="flex items-center justify-center gap-2 py-6 text-muted-foreground text-sm">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("common:loading")}
                </div>
              ) : (
                <>
                  <CommandEmpty>{resolvedEmpty}</CommandEmpty>
                  {tokens.length > 0 ? (
                    <>
                      <CommandGroup>
                        {tokens.map((token) => (
                          <CommandItem
                            key={token.value}
                            value={token.value}
                            onSelect={() => token.onToggle(!token.selected)}
                            className="cursor-pointer"
                          >
                            <div
                              className={cn(
                                "flex h-4 w-4 shrink-0 items-center justify-center rounded-sm border border-primary",
                                token.selected
                                  ? "bg-primary text-primary-foreground"
                                  : "opacity-50 [&_svg]:invisible"
                              )}
                            >
                              <Check className="h-3 w-3" />
                            </div>
                            <span className="truncate">{token.label}</span>
                          </CommandItem>
                        ))}
                      </CommandGroup>
                      <CommandSeparator />
                    </>
                  ) : null}
                  <CommandGroup>
                    {orderedResults.map((user) => {
                      const isSelected = selectedSet.has(user.id);
                      const isCurrentUser = user.id === currentUserId;
                      return (
                        <CommandItem
                          key={user.id}
                          value={String(user.id)}
                          onSelect={() => toggle(user.id)}
                          className="cursor-pointer"
                        >
                          <div
                            className={cn(
                              "flex h-4 w-4 shrink-0 items-center justify-center rounded-sm border border-primary",
                              isSelected
                                ? "bg-primary text-primary-foreground"
                                : "opacity-50 [&_svg]:invisible"
                            )}
                          >
                            <Check className="h-3 w-3" />
                          </div>
                          <MemberAvatar user={user} />
                          <span className="truncate">{getUserDisplayName(user)}</span>
                          {isCurrentUser ? (
                            <span className="text-muted-foreground text-xs">
                              {t("projects:assignee.you")}
                            </span>
                          ) : null}
                        </CommandItem>
                      );
                    })}
                  </CommandGroup>
                </>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      {variant === "default" && selectedIds.length > 0 ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => onChange([])}
          disabled={disabled}
        >
          {t("projects:assignee.clearAssignees")}
        </Button>
      ) : null}
    </div>
  );
};

// ── Single-select (user-reference property, owner reassign) ───────────────────

interface MemberSelectProps {
  scope: MemberSearchScope;
  value: number | null;
  /** The id picked, and the member it names, for a caller that shows them. */
  onChange: (id: number | null, user?: MemberSummary) => void;
  /** Display info for the current value so the trigger shows a name without a
   *  search round-trip. */
  selectedUser?: MemberLike | null;
  disabled?: boolean;
  placeholder?: string;
  emptyMessage?: string;
  className?: string;
  "aria-label"?: string;
}

export const MemberSelect = ({
  scope,
  value,
  onChange,
  selectedUser,
  disabled = false,
  placeholder,
  emptyMessage,
  className,
  "aria-label": ariaLabel,
}: MemberSelectProps) => {
  const { t } = useTranslation(["common"]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 250);

  const searchResult = useMemberSearch(scope, { search: debounced, enabled: open });
  const results = useMemo<MemberSummary[]>(
    () => searchResult.data?.items ?? [],
    [searchResult.data]
  );
  const selectedUsers = useMemo(() => (selectedUser ? [selectedUser] : undefined), [selectedUser]);
  const selectedIds = useMemo(() => (value != null ? [value] : []), [value]);
  const seen = useSeenMembers(scope, selectedIds, selectedUsers, results);

  const handleOpenChange = (next: boolean) => {
    if (disabled) return;
    setOpen(next);
    if (!next) setQuery("");
  };

  const selected = value != null ? (seen.get(value) ?? selectedUser ?? { id: value }) : null;
  const triggerLabel = selected
    ? getUserDisplayName(selected)
    : (placeholder ?? t("common:selectAnOption"));

  return (
    <div className={cn("w-full", className)}>
      <Popover open={disabled ? false : open} onOpenChange={handleOpenChange}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={!disabled && open}
            aria-label={ariaLabel}
            disabled={disabled}
            className={cn("w-full justify-between", !selected && "text-muted-foreground")}
          >
            <span className="flex min-w-0 items-center gap-2">
              {selected ? <MemberAvatar user={selected} className="h-5 w-5 text-3xs" /> : null}
              <span className="truncate">{triggerLabel}</span>
            </span>
            <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-72 p-0" align="start">
          <Command shouldFilter={false}>
            <CommandInput
              placeholder={placeholder ?? t("common:search")}
              value={query}
              onValueChange={setQuery}
            />
            <CommandList>
              {searchResult.isFetching && results.length === 0 ? (
                <div className="flex items-center justify-center gap-2 py-6 text-muted-foreground text-sm">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("common:loading")}
                </div>
              ) : (
                <>
                  <CommandEmpty>{emptyMessage ?? t("common:noResults")}</CommandEmpty>
                  <CommandGroup>
                    {value != null ? (
                      <CommandItem
                        value="__clear__"
                        onSelect={() => {
                          onChange(null);
                          handleOpenChange(false);
                        }}
                        className="cursor-pointer text-muted-foreground"
                      >
                        <X className="h-4 w-4" />
                        {t("common:clear")}
                      </CommandItem>
                    ) : null}
                    {results.map((user) => (
                      <CommandItem
                        key={user.id}
                        value={String(user.id)}
                        onSelect={() => {
                          onChange(user.id, user);
                          handleOpenChange(false);
                        }}
                        className="cursor-pointer"
                      >
                        <Check
                          className={cn(
                            "h-4 w-4 shrink-0",
                            user.id === value ? "opacity-100" : "opacity-0"
                          )}
                        />
                        <MemberAvatar user={user} />
                        <span className="truncate">{getUserDisplayName(user)}</span>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
};
