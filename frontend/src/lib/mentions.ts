/**
 * What can be named inside a comment or a document, and how it is written down.
 *
 * One trigger opens the picker over everything: `@` for people, `#` for
 * anything else. The type words after `#` — `#task:`, `#queue:` — narrow it,
 * and they are DERIVED from the generated entity types rather than listed, so
 * a tool added server-side can be mentioned the same day.
 *
 * The stored form is `#task[Label](12)`, which is shaped like a link on
 * purpose: markdown parses it before any text pass sees it, so a mention
 * written inside a code fence stays literal.
 */

import { FileType, SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { EARLIER_KINDS } from "@/lib/smartChips";

/** People. A separate trigger because they are read from the roster, not the
 *  index — identity is shared across communities, content is not. */
export const USER_TRIGGER = "@";

/** Everything else. */
export const ENTITY_TRIGGER = "#";

/**
 * The characters a typed name may not carry, mirroring the backend's
 * ``RESERVED_SIGILS``. They are the two triggers above: a name is the thing a
 * mention points AT, so it does not also get to spell one. Derived from the
 * triggers rather than listed again, so the two sides say it once each.
 */
export const RESERVED_SIGILS: readonly string[] = [USER_TRIGGER, ENTITY_TRIGGER];

/** Whether a typed name carries one, so a form can say so before it submits. */
export const hasReservedSigil = (value: string): boolean =>
  RESERVED_SIGILS.some((sigil) => value.includes(sigil));

/**
 * What a `#` can reach: everything indexed except what people SAID about it.
 * A comment is not a thing you name — it is a remark on one, and the thing it
 * is on is what a reader wants.
 */
export const MENTIONABLE_TYPES: SearchEntityType[] = Object.values(SearchEntityType).filter(
  (type) => type !== SearchEntityType.comment
);

/** The word after `#` that narrows to one type: the type's own name, kebabed. */
export const typeTrigger = (type: SearchEntityType): string => type.replaceAll("_", "-");

/**
 * Trigger word -> type. Longest first, so `#counter-group` is not read as
 * `#counter` with a stray suffix.
 */
const TRIGGER_TYPES: [string, SearchEntityType][] = [
  ...MENTIONABLE_TYPES.map((type): [string, SearchEntityType] => [typeTrigger(type), type]),
  // Written by every composer before the type words were derived, and still
  // sitting in stored comments, so it is read as well as the derived spelling.
  ["doc", SearchEntityType.file] as [string, SearchEntityType],
  // A kind's earlier spelling, still sitting in stored text.
  ...Object.entries(EARLIER_KINDS).map(([kind, type]): [string, SearchEntityType] => [
    kind.replaceAll("_", "-"),
    type,
  ]),
].sort((a, b) => b[0].length - a[0].length);

/** The type a trigger word names, or `undefined` if it names none. */
export const typeForTrigger = (word: string): SearchEntityType | undefined =>
  TRIGGER_TYPES.find(([trigger]) => trigger === word)?.[1];

/** Every trigger word, longest first — what a parser matches against. */
export const TRIGGER_WORDS: string[] = TRIGGER_TYPES.map(([trigger]) => trigger);

/** A label is written into the text, so the characters the syntax is built
 *  from cannot appear inside it. */
const mentionLabel = (label: string): string => label.replace(/[[\]()]/g, "");

/** How a chosen suggestion is written into a comment. */
export const entityMentionSyntax = (type: SearchEntityType, label: string, id: number): string =>
  `${ENTITY_TRIGGER}${typeTrigger(type)}[${mentionLabel(label)}](${id})`;

/** How a chosen person is written into a comment. */
export const userMentionSyntax = (label: string, id: number): string =>
  `${USER_TRIGGER}[${mentionLabel(label)}](${id})`;

/** Opens the picker over the tools, and can make one that is not there. */
export const LINK_TRIGGER_OPEN = "[[";

/** What the composer is being asked for right now. */
export type MentionQuery = {
  /** `null` while typing after a bare `#` — every type is offered. */
  types: SearchEntityType[] | null;
  /** What has been typed after the trigger. */
  query: string;
  /** How many characters of the field the mention occupies, so replacing it
   *  removes the trigger too. */
  length: number;
};

/** A mention being typed: people, or things. */
export type ActiveMention = MentionQuery & {
  user: boolean;
  /** Typed with `[[`, which offers to make what it cannot find. */
  canCreate: boolean;
};

//: `@word`, or `#word`, or `#type:word` — anchored to the end of what has been
//: typed, and only at a word boundary so an email address is not a mention.
const USER_PATTERN = /(^|[\s([{])@([^\s@#]*)$/;
const ENTITY_PATTERN = /(^|[\s([{])#([\w-]*)(?::([^\s#]*))?$/;
//: `[[name` — open brackets, then whatever is being named. Closing them is
//: not required: the picker commits, the way it does for `@` and `#`.
const LINK_PATTERN = /\[\[([^\]\n]*)$/;

/**
 * The mention being typed at the end of `text`, or `null`.
 *
 * `#ven` is ambiguous — it could be a type word half-typed, or a search for
 * "ven" across everything — so it is treated as both: the search runs over
 * every type, and typing `:` is what commits to narrowing.
 */
export const activeMention = (text: string): ActiveMention | null => {
  const user = USER_PATTERN.exec(text);
  if (user) {
    return {
      user: true,
      canCreate: false,
      types: null,
      query: user[2],
      length: user[2].length + 1,
    };
  }

  // `[[` before `#`: the two cannot overlap, but the link trigger is the more
  // specific of them and reads its own brackets.
  const link = LINK_PATTERN.exec(text);
  if (link) {
    return {
      user: false,
      canCreate: true,
      // The caller narrows to the tools this initiative has; a reference to
      // anything else is what `#` is for.
      types: null,
      query: link[1],
      length: link[1].length + LINK_TRIGGER_OPEN.length,
    };
  }

  const entity = ENTITY_PATTERN.exec(text);
  if (!entity) return null;
  const [, , word, narrowed] = entity;
  if (narrowed === undefined) {
    return { user: false, canCreate: false, types: null, query: word, length: word.length + 1 };
  }
  const type = typeForTrigger(word);
  if (!type) return null;
  return {
    user: false,
    canCreate: false,
    types: [type],
    query: narrowed,
    length: word.length + narrowed.length + 2,
  };
};

/**
 * Whether a document offers `#`.
 *
 * Only a standard document does. A whiteboard and a spreadsheet hold their
 * content in shapes and cells rather than prose, and a file or a linked page
 * has no body of its own to write in — none of them has a line of text with a
 * caret in it for a trigger to be typed into.
 */
export const supportsEntityMentions = (type: FileType | null | undefined): boolean =>
  type === FileType.lexical;
