import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import {
  LexicalTypeaheadMenuPlugin,
  MenuOption,
  type MenuTextMatch,
} from "@lexical/react/LexicalTypeaheadMenuPlugin";
import { useNavigate } from "@tanstack/react-router";
import { CLICK_COMMAND, COMMAND_PRIORITY_LOW, type TextNode } from "lexical";
import { type JSX, useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import type { SearchSuggestion } from "@/api/generated/initiativeAPI.schemas";
import { $createEntityMentionNode } from "@/components/editor/nodes/entity-mention-node";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityPickerSuggestions } from "@/hooks/useSearch";
import { communityPath } from "@/lib/communityUrl";
import { entityRefTypeFor } from "@/lib/entityResolver";
import { activeMention, ENTITY_TRIGGER, MENTIONABLE_TYPES } from "@/lib/mentions";
import { hitIcon } from "@/lib/searchResults";
import { entityRefRoute } from "@/lib/tools";
import { Command, CommandGroup, CommandItem, CommandList } from "@/ui/command";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";

/** How many things the `#` menu offers at once. */
const SUGGESTION_LIMIT = 5;

class EntityOption extends MenuOption {
  constructor(readonly suggestion: SearchSuggestion) {
    super(`${suggestion.entity_type}-${suggestion.entity_id}`);
  }
}

/**
 * The mention being typed at the caret, in the shape Lexical's typeahead wants.
 *
 * `activeMention` is the same reader the comment composer uses, so `#` behaves
 * identically in a document and in a comment — including narrowing with
 * `#task:` and the kinds that derive from the entity types.
 */
export function entityMatch(text: string): MenuTextMatch | null {
  const active = activeMention(text);
  if (!active || active.user) return null;
  const replaceable = text.slice(text.length - active.length);
  return {
    leadOffset: text.length - active.length,
    // Everything after the `#`, type word included, so the narrowing is not
    // lost on the way through Lexical — the menu reads it back below.
    matchingString: replaceable.slice(ENTITY_TRIGGER.length),
    replaceableString: replaceable,
  };
}

export interface EntityMentionsPluginProps {
  /** Initiative the document belongs to — what a mention may reach. */
  initiativeId?: number | null;
  /** The thing being written in, as a reference (`file:12`). Never
   *  offered: a thing does not point at itself. */
  subject?: string | null;
}

/**
 * `#` in a document, offering everything in its initiative.
 *
 * Mounted only for a standard document: a whiteboard and a spreadsheet are not
 * prose and have no caret to type a trigger into, and a file or a linked page
 * has no editable body at all.
 */
export function EntityMentionsPlugin({
  initiativeId,
  subject,
}: EntityMentionsPluginProps): JSX.Element | null {
  const [editor] = useLexicalComposerContext();
  const { t } = useTranslation("editor");
  const navigate = useNavigate();
  const communityId = useActiveCommunityId();
  const [queryString, setQueryString] = useState<string | null>(null);
  // Read back through the same parser the comment composer uses, so `#task:`
  // narrows here exactly as it does there.
  const active = useMemo(
    () => (queryString === null ? null : activeMention(`${ENTITY_TRIGGER}${queryString}`)),
    [queryString]
  );
  const typedQuery = active?.query ?? "";
  const debouncedQuery = useDebouncedValue(typedQuery, 200);

  // The one lookup every picker in the app goes through, narrowed to this
  // initiative's live work. A bare `#` names nothing yet, so it opens on what
  // was most recently worked on rather than on a menu with nothing in it.
  const { items, isFetching, stale } = useCommunityPickerSuggestions(debouncedQuery, {
    types: active?.types ?? MENTIONABLE_TYPES,
    initiative_id: initiativeId ?? undefined,
    is_template: false,
    subject,
    limit: SUGGESTION_LIMIT,
    enabled: active !== null && (initiativeId ?? 0) > 0,
  });

  // The previous answer stays on screen while the next is in flight, so the
  // menu does not blink shut between keystrokes. Typing `:` narrows the kinds
  // faster than the answer can arrive, though, so what is on screen is held to
  // the kinds asked for now — pressing Enter can only ever insert one of them.
  const wanted = active?.types;
  const shown = useMemo(
    () =>
      items
        .filter((suggestion) => !wanted || wanted.includes(suggestion.entity_type))
        .map((suggestion) => new EntityOption(suggestion)),
    [items, wanted]
  );
  // Nothing held over from a query the reader has moved on from is offered to
  // the keyboard, so Enter cannot land on a thing they have stopped naming.
  const options = useMemo(() => (stale ? [] : shown), [stale, shown]);
  // Until the debounce catches up, the answer on screen is for an earlier query.
  const searching = isFetching || debouncedQuery !== typedQuery;

  const onSelectOption = useCallback(
    (option: EntityOption, nodeToReplace: TextNode | null, closeMenu: () => void) => {
      editor.update(() => {
        const node = $createEntityMentionNode(
          option.suggestion.entity_type,
          option.suggestion.entity_id,
          option.suggestion.title
        );
        if (nodeToReplace) nodeToReplace.replace(node);
        // A decorator has no caret of its own; put it after the reference so
        // typing continues in the sentence.
        node.selectNext();
        closeMenu();
      });
    },
    [editor]
  );

  // A mention names a thing; clicking it opens that thing. The address of an
  // entity includes its initiative, which a mention does not carry, so this
  // goes through the `/go` resolver like every other bare-id link.
  useEffect(() => {
    return editor.registerCommand(
      CLICK_COMMAND,
      (event: MouseEvent) => {
        const target = event.target as HTMLElement | null;
        const type = target?.getAttribute("data-lexical-entity-mention");
        const id = Number(target?.getAttribute("data-entity-id"));
        if (!type || !Number.isFinite(id)) return false;
        const refType = entityRefTypeFor(type as SearchSuggestion["entity_type"]);
        if (!refType) return false;
        event.preventDefault();
        void navigate({ to: communityPath(communityId, entityRefRoute(refType, id)) });
        return true;
      },
      COMMAND_PRIORITY_LOW
    );
  }, [editor, navigate, communityId]);

  if (!initiativeId) return null;

  return (
    <LexicalTypeaheadMenuPlugin<EntityOption>
      onQueryChange={setQueryString}
      onSelectOption={onSelectOption}
      triggerFn={entityMatch}
      options={options}
      menuRenderFn={(anchorElementRef, { selectedIndex, selectOptionAndCleanUp }) =>
        anchorElementRef.current
          ? createPortal(
              <div className="absolute z-10 w-[260px] rounded-md shadow-md">
                <Command>
                  <CommandList>
                    {shown.length ? (
                      <CommandGroup>
                        {shown.map((option, index) => {
                          const Icon = hitIcon(option.suggestion);
                          return (
                            <CommandItem
                              key={option.key}
                              value={option.key}
                              onSelect={() => !stale && selectOptionAndCleanUp(option)}
                              disabled={stale}
                              className={`flex items-center gap-2 ${
                                selectedIndex === index ? "bg-accent" : "bg-transparent!"
                              } ${stale ? "opacity-50" : ""}`}
                            >
                              <Icon className="h-4 w-4 shrink-0" />
                              <span className="truncate">{option.suggestion.title}</span>
                            </CommandItem>
                          );
                        })}
                      </CommandGroup>
                    ) : (
                      // Rendering nothing here is what made `#` look broken: a
                      // reference is scoped to this document's initiative, so a
                      // community full of matches can still leave a reader staring
                      // at an unchanged caret with no idea why.
                      <div className="space-y-1 px-3 py-2">
                        <p className="text-muted-foreground text-sm">
                          {searching
                            ? t("references.searching")
                            : t("references.noMatches", { query: typedQuery })}
                        </p>
                        {!searching && (
                          <p className="text-muted-foreground/80 text-xs">
                            {t("references.scopeHint")}
                          </p>
                        )}
                      </div>
                    )}
                  </CommandList>
                </Command>
              </div>,
              anchorElementRef.current
            )
          : null
      }
    />
  );
}
