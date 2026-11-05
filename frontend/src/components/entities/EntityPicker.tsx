import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type EndpointRef,
  SearchEntityType,
  type SearchSuggestion,
} from "@/api/generated/initiativeAPI.schemas";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { useCommunityPickerSuggestions } from "@/hooks/useSearch";
import type { ItemEndKind } from "@/lib/relationships";
import { hitIcon } from "@/lib/searchResults";

/**
 * The kinds a relation picker offers, derived from the generated enum so a kind
 * added server-side is offered here without an edit.
 *
 * Two are left out. A **comment** is not referenceable at all, so no edge may
 * name one. A **tag** may sit on an edge — that is how tagging is stored — but
 * it is chosen with the tag picker, because a label is not something you pick a
 * relationship type for.
 */
export const LINKABLE_TYPES: SearchEntityType[] = Object.values(SearchEntityType).filter(
  (type) => type !== SearchEntityType.comment && type !== SearchEntityType.tag
);

/** A suggestion that can be a link end: what this picker hands back. */
export type LinkableSuggestion = SearchSuggestion & { entity_type: ItemEndKind };

const isLinkable = (item: SearchSuggestion): item is LinkableSuggestion =>
  item.entity_type !== SearchEntityType.comment;

interface EntityPickerProps {
  /**
   * The thing being linked from, so it is never offered as its own far end.
   * Absent while linking from something that does not exist yet — a queue item
   * being composed — where there is no self to leave out.
   */
  subject?: EndpointRef;
  /** Links made here stay inside one initiative, which the server enforces. */
  initiativeId: number | null;
  /** Narrow what may be picked. Defaults to every kind an edge may name. */
  types?: SearchEntityType[];
  value: LinkableSuggestion | null;
  onChange: (value: LinkableSuggestion | null) => void;
  disabled?: boolean;
}

/**
 * Where a suggestion lives, as one line under its name.
 *
 * The name on its own is often not a choice anybody can make: six projects run
 * from one template hold six tasks called "Do a thing", and the project is the
 * only thing that tells them apart.
 *
 * The initiative is named only when the picker is not already confined to one
 * — inside a single initiative it is the same word on every row, which is
 * noise rather than context.
 */
const whereItLives = (item: SearchSuggestion, initiativeId: number | null): string | undefined => {
  const parts = [initiativeId == null ? item.initiative_name : null, item.tool_title].filter(
    (part): part is string => Boolean(part?.trim())
  );
  return parts.length ? parts.join(" · ") : undefined;
};

/**
 * Pick one thing of any kind.
 *
 * The search that backs it is the same one every other picker in the app uses,
 * only without a kind narrowed down to one — so it offers what somebody looked
 * at recently before anything is typed, and matches by name once something is.
 * Each row says what kind of thing it is, and where it lives, because in a list
 * drawn from thirteen kinds a name alone often is not enough to tell two apart
 * — nor is it within one kind, once a template has been run six times.
 *
 * It hands back the whole suggestion rather than an id: the caller needs the
 * kind to build the edge, and the title to keep showing what is selected after
 * the query has moved on.
 */
export const EntityPicker = ({
  subject,
  initiativeId,
  types,
  value,
  onChange,
  disabled,
}: EntityPickerProps) => {
  const { t } = useTranslation(["relations", "search"]);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const suggestions = useCommunityPickerSuggestions(query, {
    types: types ?? LINKABLE_TYPES,
    initiative_id: initiativeId ?? undefined,
    // A template's contents are not what somebody is reaching for here.
    is_template: false,
    subject: subject ? `${subject.type}:${subject.id}` : undefined,
    enabled: open,
  });

  const byValue = useMemo(() => {
    const map = new Map<string, LinkableSuggestion>();
    for (const item of suggestions.items) {
      if (isLinkable(item)) map.set(`${item.entity_type}:${item.entity_id}`, item);
    }
    return map;
  }, [suggestions.items]);

  const items = useMemo(
    () =>
      suggestions.items.map((item) => ({
        value: `${item.entity_type}:${item.entity_id}`,
        label: item.title,
        icon: hitIcon(item),
        hint: t(`search:types.${item.entity_type}`, { defaultValue: item.entity_type }),
        sublabel: whereItLives(item, initiativeId),
      })),
    [suggestions.items, initiativeId, t]
  );

  return (
    <AsyncCombobox
      items={items}
      value={value ? `${value.entity_type}:${value.entity_id}` : null}
      // What was picked, said the same way the row said it — otherwise the
      // button reads "Do a thing" and the choice cannot be checked.
      selectedLabel={
        value ? [value.title, whereItLives(value, initiativeId)].filter(Boolean).join(" · ") : null
      }
      onValueChange={(next) => onChange(byValue.get(next) ?? null)}
      onSearchChange={setQuery}
      onOpenChange={setOpen}
      loading={suggestions.isLoading}
      placeholder={t("relations:dialog.entityPlaceholder")}
      searchPlaceholder={t("relations:dialog.entityPlaceholder")}
      emptyMessage={t("relations:dialog.noResults")}
      aria-label={t("relations:dialog.entity")}
      disabled={disabled}
    />
  );
};
