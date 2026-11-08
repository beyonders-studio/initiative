import type { TFunction } from "i18next";
import { Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { SearchSuggestion, UserSummary } from "@/api/generated/initiativeAPI.schemas";
import { useInitiative } from "@/hooks/useInitiatives";
import { useCommunityPickerSuggestions } from "@/hooks/useSearch";
import { type MemberSearchScope, useMemberSearch } from "@/hooks/useUsers";
import { getInitials } from "@/lib/initials";
import type { ActiveMention } from "@/lib/mentions";
import { MENTIONABLE_TYPES } from "@/lib/mentions";
import { linkableToolTypes } from "@/lib/references";
import { hitIcon } from "@/lib/searchResults";
import { getAvatarSrc, getUserDisplayName, getUserHandle } from "@/lib/userDisplay";
import { Avatar, AvatarFallback, AvatarImage } from "@/ui/avatar";
import { cn } from "@/ui/lib/utils";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";

/** How many rows a mention picker offers. */
const MENTION_LIMIT = 8;

/** What choosing a row means: a person, or one of the things in this community. */
export type MentionChoice =
  | { user: true; id: number; label: string; member: UserSummary }
  | { user: false; suggestion: SearchSuggestion }
  /** Nothing matched and `[[ ]]` offered to make it. */
  | { user: false; create: string };

interface MentionPopoverProps {
  /** The mention being typed — who or what, and how much of it. */
  active: ActiveMention;
  initiativeId: number;
  /** The thing this comment is on, as a reference (`file:12`). Never
   *  offered: a remark about something does not point back at it. */
  subject?: string | null;
  /** Who `@` offers: the initiative's members unless this says otherwise. */
  members?: MemberSearchScope;
  /** Pixel anchor (relative to the field) so the popover sits under the word
   *  being typed. Falls back to below the whole field when absent. */
  anchor?: { top: number; left: number } | null;
  onSelect: (choice: MentionChoice) => void;
  onClose: () => void;
}

/** One offered row, reduced to what the list renders. */
interface Row {
  key: string;
  label: string;
  subtitle: string | null;
  leading: React.ReactNode;
  choose: MentionChoice;
}

const memberRow = (member: UserSummary): Row => {
  const src = getAvatarSrc(member);
  const label = getUserDisplayName(member);
  const handle = getUserHandle(member);
  return {
    key: `user-${member.id}`,
    label,
    // The handle under the name is what tells two people of the same name
    // apart. Nothing to add when the line above already IS the handle.
    subtitle: handle === label ? null : handle,
    leading: (
      <Avatar className="h-5 w-5 shrink-0 text-3xs">
        {src ? <AvatarImage src={src} alt={label} /> : null}
        <AvatarFallback userId={member.id}>{getInitials(label)}</AvatarFallback>
      </Avatar>
    ),
    choose: { user: true, id: member.id, label, member },
  };
};

const createRow = (name: string, t: TFunction<["comments", "common"]>): Row => ({
  key: `create-${name}`,
  label: t("createNamed", { name }),
  subtitle: null,
  leading: <Plus className="h-4 w-4 shrink-0" />,
  choose: { user: false, create: name },
});

const suggestionRow = (suggestion: SearchSuggestion): Row => {
  const Icon = hitIcon(suggestion);
  return {
    key: `${suggestion.entity_type}-${suggestion.entity_id}`,
    label: suggestion.title,
    subtitle: null,
    leading: <Icon className="h-4 w-4 shrink-0" />,
    choose: { user: false, suggestion },
  };
};

/**
 * The list under a half-typed `@` or `#`.
 *
 * People come from the initiative's roster and everything else from the search
 * index — the same two reads the results page makes, for the same reason: a
 * person exists across communities, content exists in one.
 */
export const MentionPopover = ({
  active,
  initiativeId,
  subject,
  members: memberScope,
  anchor,
  onSelect,
  onClose,
}: MentionPopoverProps) => {
  const { t } = useTranslation(["comments", "common"]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const popoverRef = useRef<HTMLDivElement>(null);

  const positionClass = anchor ? "" : "top-full left-0 mt-1";
  const positionStyle = anchor ? { top: anchor.top, left: anchor.left } : undefined;

  // A community-level surface — a community calendar, say — belongs to no
  // initiative, so there is nothing initiative-scoped to offer.
  const inInitiative = initiativeId > 0;
  const members = useMemberSearch(memberScope ?? { type: "initiative", initiativeId }, {
    search: active.query,
    pageSize: MENTION_LIMIT,
    enabled: active.user && (memberScope !== undefined || inInitiative),
  });
  // `[[ ]]` reaches the tools this initiative has; `#` reaches everything.
  // Held across renders, so the rows below are rebuilt only when what they
  // come from changes, and moving through them doesn't start them over.
  const { data: initiative } = useInitiative(inInitiative ? initiativeId : null);
  const types = useMemo(
    () => (active.canCreate ? linkableToolTypes(initiative) : (active.types ?? MENTIONABLE_TYPES)),
    [active.canCreate, active.types, initiative]
  );
  // A bare trigger names nothing yet, so the list opens on what was most
  // recently worked on instead of on nothing at all.
  const suggestions = useCommunityPickerSuggestions(active.query, {
    types,
    initiative_id: initiativeId,
    // A mention points at work, not at the blueprint work is started from.
    is_template: false,
    subject,
    limit: MENTION_LIMIT,
    enabled: !active.user && inInitiative,
  });

  // The previous answer stays on screen while the next is in flight. Typing `:`
  // narrows the kinds faster than the answer can arrive, so what is on screen
  // is held to the kinds asked for now rather than the ones asked for a
  // keystroke ago.
  const wanted = active.canCreate ? types : active.types;
  const rows: Row[] = useMemo(() => {
    if (active.user) return (members.data?.items ?? []).map(memberRow);
    const found = suggestions.items
      .filter((suggestion) => !wanted || wanted.includes(suggestion.entity_type))
      .map(suggestionRow);
    if (!active.canCreate || !active.query.trim()) return found;
    // `[[ ]]` is the trigger that can make what it cannot find. The option is
    // last, so it never sits where an existing thing was about to be picked.
    const named = active.query.trim().toLowerCase();
    if (found.some((row) => row.label.toLowerCase() === named)) return found;
    return [...found, createRow(active.query.trim(), t)];
  }, [active.user, active.canCreate, active.query, wanted, members.data, suggestions.items, t]);

  const isLoading = active.user
    ? (memberScope !== undefined || inInitiative) && members.isLoading
    : inInitiative && suggestions.isLoading;

  // A new list starts at its top.
  const [prevRows, setPrevRows] = useState(rows);
  if (prevRows !== rows) {
    setPrevRows(rows);
    setSelectedIndex(0);
  }

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!rows.length) return;
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          e.stopPropagation();
          setSelectedIndex((prev) => (prev + 1) % rows.length);
          break;
        case "ArrowUp":
          e.preventDefault();
          e.stopPropagation();
          setSelectedIndex((prev) => (prev - 1 + rows.length) % rows.length);
          break;
        case "Enter":
        case "Tab":
          e.preventDefault();
          e.stopPropagation();
          if (rows[selectedIndex]) onSelect(rows[selectedIndex].choose);
          break;
        case "Escape":
          e.preventDefault();
          e.stopPropagation();
          onClose();
          break;
      }
    },
    [rows, selectedIndex, onSelect, onClose]
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [handleKeyDown]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [onClose]);

  const shell = cn(
    "absolute z-50 w-64 rounded-md border bg-popover text-popover-foreground shadow-md",
    positionClass
  );

  if (isLoading) {
    return (
      <div ref={popoverRef} style={positionStyle} className={cn(shell, "p-2")}>
        <SkeletonRegion>
          <ListSkeleton rows={3} />
        </SkeletonRegion>
      </div>
    );
  }

  if (!rows.length) {
    return (
      <div ref={popoverRef} style={positionStyle} className={cn(shell, "p-2")}>
        <p className="text-muted-foreground text-sm">
          {active.user ? t("noPeople") : t("noMatches")}
        </p>
      </div>
    );
  }

  return (
    <div ref={popoverRef} style={positionStyle} className={cn(shell, "overflow-hidden")}>
      <div className="max-h-48 overflow-y-auto">
        {rows.map((row, index) => (
          <button
            key={row.key}
            type="button"
            onClick={() => onSelect(row.choose)}
            className={cn(
              "flex w-full cursor-pointer items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-accent",
              index === selectedIndex && "bg-accent"
            )}
          >
            {row.leading}
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium">{row.label}</p>
              {row.subtitle && (
                <p className="truncate text-muted-foreground text-xs">{row.subtitle}</p>
              )}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
};
