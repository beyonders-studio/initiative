import { Users, X } from "lucide-react";
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
import { Combobox } from "@/ui/combobox";
import { cn } from "@/ui/lib/utils";

/** The slim user shape these pickers render (the search endpoints' `UserSummary`). */
type MemberSummary = Pick<
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

  const searchResult = useMemberSearch(scope, { search: query, enabled: open });
  const results = useMemo<MemberSummary[]>(
    () => searchResult.data?.items ?? [],
    [searchResult.data]
  );
  const seen = useSeenMembers(scope, selectedIds, selectedUsers, results);

  const resolvedPlaceholder = placeholder ?? t("projects:assignee.searchPlaceholder");

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

  // A token changed, or else a person did: one row is toggled at a time.
  const handleValueChange = (next: string[]) => {
    const token = tokens.find((each) => next.includes(each.value) !== each.selected);
    if (token) return token.onToggle(!token.selected);
    onChange(next.filter((value) => !tokens.some((each) => each.value === value)).map(Number));
  };

  const picker = (
    <Combobox
      multiple
      id={id}
      className={className}
      items={[
        ...tokens.map((token) => ({ value: token.value, label: token.label })),
        ...orderedResults.map((user) => ({
          value: String(user.id),
          label: getUserDisplayName(user),
          icon: <MemberAvatar user={user} />,
          hint: user.id === currentUserId ? t("projects:assignee.you") : undefined,
        })),
      ]}
      value={[
        ...tokens.filter((token) => token.selected).map((token) => token.value),
        ...selectedIds.map(String),
      ]}
      onValueChange={handleValueChange}
      onSearchChange={setQuery}
      onOpenChange={setOpen}
      loading={searchResult.isFetching && results.length === 0}
      placeholder={resolvedPlaceholder}
      searchPlaceholder={resolvedPlaceholder}
      emptyMessage={emptyMessage ?? t("projects:assignee.emptyMessage")}
      disabled={disabled}
      trigger={
        variant === "default" ? (
          <Button
            id={id}
            variant="outline"
            role="combobox"
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
                          if (!disabled) onChange(selectedIds.filter((value) => value !== id));
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
        ) : undefined
      }
    />
  );

  // "filter" is the field alone; "default" also offers to clear it.
  if (variant === "filter") return picker;
  return (
    <div className={cn("space-y-3", className)}>
      {picker}
      {selectedIds.length > 0 ? (
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
