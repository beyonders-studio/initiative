import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import {
  LexicalTypeaheadMenuPlugin,
  MenuOption,
  type MenuTextMatch,
  useBasicTypeaheadTriggerMatch,
} from "@lexical/react/LexicalTypeaheadMenuPlugin";
import type { TextNode } from "lexical";
import { type JSX, useCallback, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { $createMentionNode } from "@/components/editor/nodes/mention-node";
import { useInitiativeMemberSearch } from "@/hooks/useUsers";
import { getInitials } from "@/lib/initials";
import { getAvatarSrc, getUserDisplayName } from "@/lib/userDisplay";
import { Avatar, AvatarFallback, AvatarImage } from "@/ui/avatar";
import { Command, CommandGroup, CommandItem, CommandList } from "@/ui/command";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";

const PUNCTUATION = "\\.,\\+\\*\\?\\$\\@\\|#{}\\(\\)\\^\\-\\[\\]\\\\/!%'\"~=<>_:;";
const NAME = "\\b[A-Z][^\\s" + PUNCTUATION + "]";

const DocumentMentionsRegex = {
  NAME,
  PUNCTUATION,
};

const PUNC = DocumentMentionsRegex.PUNCTUATION;

const TRIGGERS = ["@"].join("");

// Chars we expect to see in a mention (non-space, non-punctuation).
const VALID_CHARS = "[^" + TRIGGERS + PUNC + "\\s]";

// Non-standard series of chars. Each series must be preceded and followed by
// a valid char.
const VALID_JOINS =
  "(?:" +
  "\\.[ |$]|" + // E.g. "r. " in "Mr. Smith"
  " |" + // E.g. " " in "Josh Duck"
  "[" +
  PUNC +
  "]|" + // E.g. "-' in "Salier-Hellendag"
  ")";

const LENGTH_LIMIT = 75;

const AtSignMentionsRegex = new RegExp(
  "(^|\\s|\\()(" +
    "[" +
    TRIGGERS +
    "]" +
    "((?:" +
    VALID_CHARS +
    VALID_JOINS +
    "){0," +
    LENGTH_LIMIT +
    "})" +
    ")$"
);

// 50 is the longest alias length limit.
const ALIAS_LENGTH_LIMIT = 50;

// Regex used to match alias.
const AtSignMentionsRegexAliasRegex = new RegExp(
  "(^|\\s|\\()(" +
    "[" +
    TRIGGERS +
    "]" +
    "((?:" +
    VALID_CHARS +
    "){0," +
    ALIAS_LENGTH_LIMIT +
    "})" +
    ")$"
);

// At most, 5 suggestions are shown in the popup.
const SUGGESTION_LIST_LENGTH_LIMIT = 5;

function checkForAtSignMentions(text: string, minMatchLength: number): MenuTextMatch | null {
  let match = AtSignMentionsRegex.exec(text);

  if (match === null) {
    match = AtSignMentionsRegexAliasRegex.exec(text);
  }
  if (match !== null) {
    // The strategy ignores leading whitespace but we need to know it's
    // length to add it to the leadOffset

    const maybeLeadingWhitespace = match[1];

    const matchingString = match[3];
    if (matchingString.length >= minMatchLength) {
      return {
        leadOffset: match.index + maybeLeadingWhitespace.length,
        matchingString,
        replaceableString: match[2],
      };
    }
  }
  return null;
}

function getPossibleQueryMatch(text: string): MenuTextMatch | null {
  return checkForAtSignMentions(text, 0);
}

class MentionTypeaheadOption extends MenuOption {
  name: string;
  userId: number;
  picture: JSX.Element;

  constructor(name: string, userId: number, picture: JSX.Element) {
    super(name);
    this.name = name;
    this.userId = userId;
    this.picture = picture;
  }
}

export interface MentionsPluginProps {
  /** Initiative the document belongs to — scopes the server-side member
   *  search that backs mention suggestions. */
  initiativeId?: number;
}

export function MentionsPlugin({ initiativeId }: MentionsPluginProps): JSX.Element | null {
  const [editor] = useLexicalComposerContext();

  const [queryString, setQueryString] = useState<string | null>(null);
  const debouncedQuery = useDebouncedValue(queryString ?? "", 200);

  // The initiative's roster — the same read every other people picker makes,
  // so a name typed nearly right finds its person here too.
  const { data } = useInitiativeMemberSearch(initiativeId, {
    search: debouncedQuery,
    pageSize: SUGGESTION_LIST_LENGTH_LIMIT,
    enabled: (initiativeId ?? 0) > 0 && queryString !== null,
  });

  const options = useMemo(
    () =>
      (data?.items ?? []).map((member) => {
        const avatarSrc = getAvatarSrc(member);
        const name = getUserDisplayName(member);
        return new MentionTypeaheadOption(
          name,
          member.id,
          <Avatar className="h-5 w-5 text-3xs">
            {avatarSrc ? <AvatarImage src={avatarSrc} alt={name} /> : null}
            <AvatarFallback userId={member.id}>{getInitials(name)}</AvatarFallback>
          </Avatar>
        );
      }),
    [data]
  );

  const checkForSlashTriggerMatch = useBasicTypeaheadTriggerMatch("/", {
    minLength: 0,
  });

  const onSelectOption = useCallback(
    (
      selectedOption: MentionTypeaheadOption,
      nodeToReplace: TextNode | null,
      closeMenu: () => void
    ) => {
      editor.update(() => {
        const mentionNode = $createMentionNode(selectedOption.name, selectedOption.userId);
        if (nodeToReplace) {
          nodeToReplace.replace(mentionNode);
        }
        // A decorator has no text to put a caret in, so the caret goes after
        // it — which is where the writer was going to type anyway.
        mentionNode.selectNext();
        closeMenu();
      });
    },
    [editor]
  );

  const checkForMentionMatch = useCallback(
    (text: string) => {
      const slashMatch = checkForSlashTriggerMatch(text, editor);
      if (slashMatch !== null) {
        return null;
      }
      return getPossibleQueryMatch(text);
    },
    [checkForSlashTriggerMatch, editor]
  );

  if (!initiativeId) {
    return null;
  }

  return (
    <LexicalTypeaheadMenuPlugin<MentionTypeaheadOption>
      onQueryChange={setQueryString}
      onSelectOption={onSelectOption}
      triggerFn={checkForMentionMatch}
      options={options}
      menuRenderFn={(
        anchorElementRef,
        { selectedIndex, selectOptionAndCleanUp, setHighlightedIndex }
      ) => {
        return anchorElementRef.current && options.length
          ? createPortal(
              <div className="absolute z-10 w-[250px] rounded-md shadow-md">
                <Command
                  onKeyDown={(e) => {
                    if (e.key === "ArrowUp") {
                      e.preventDefault();
                      setHighlightedIndex(
                        selectedIndex !== null
                          ? (selectedIndex - 1 + options.length) % options.length
                          : options.length - 1
                      );
                    } else if (e.key === "ArrowDown") {
                      e.preventDefault();
                      setHighlightedIndex(
                        selectedIndex !== null ? (selectedIndex + 1) % options.length : 0
                      );
                    }
                  }}
                >
                  <CommandList>
                    <CommandGroup>
                      {options.map((option, index) => (
                        <CommandItem
                          key={option.key}
                          value={option.name}
                          onSelect={() => {
                            selectOptionAndCleanUp(option);
                          }}
                          className={`flex items-center gap-2 ${
                            selectedIndex === index ? "bg-accent" : "bg-transparent!"
                          }`}
                        >
                          {option.picture}
                          <span className="truncate">{option.name}</span>
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  </CommandList>
                </Command>
              </div>,
              anchorElementRef.current
            )
          : null;
      }}
    />
  );
}
