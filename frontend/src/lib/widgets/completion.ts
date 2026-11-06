/**
 * What to offer somebody typing a statement.
 *
 * Deliberately not a parser. The validator is the only thing that reads SQL
 * properly, and a second reading of it here would be a second thing to keep
 * right — so this works on words: what is being typed, and which of the names
 * the server says exist start with it.
 *
 * That is enough because the vocabulary is closed and small. The server serves
 * both halves of it (`/query/vocabulary` and `/fields/{dataset}`), so a name
 * offered here is one the validator accepts, and a dataset or function added
 * there reaches this without an edit.
 *
 * One concession to context: when the text already names datasets, only those
 * datasets' fields are offered. That is a set intersection over words, not a
 * `FROM` clause being read — being wrong about it costs a suggestion, never a
 * statement, because nothing is completed that the author does not choose.
 *
 * A spreadsheet's range is read by `sheet('<name>', '<range>')`, so inside the
 * quote that opens one the initiative's spreadsheets are offered by name. What
 * a range holds is known only once the statement has been checked, which reads
 * it; those columns are offered under the name the range is read under.
 */

/** The word a completion replaces: what a name may be spelled with. */
const WORD = /[A-Za-z0-9_]+$/;

/** What kind of thing a suggestion is, for the icon and the grouping. */
export type CompletionKind =
  | "dataset"
  | "field"
  | "function"
  | "token"
  | "relation"
  | "spreadsheet";

export interface Completion {
  /** The text inserted, and what is matched against. */
  name: string;
  kind: CompletionKind;
  /** Where a field comes from, or what a function does to its argument. */
  detail?: string;
}

/** The dataset a field belongs to, its fields, and what it can be read
 *  alongside. */
export interface DatasetFields {
  dataset: string;
  fields: { name: string; type: string }[];
  /** What this dataset declares a way to reach. A field of one is named
   *  `<relation>.<field>`, and the join is the server's to write. */
  relations?: { name: string; dataset: string }[];
}

/** A name that qualifies the one being typed: `assignee.disp`. */
const QUALIFIED = /([A-Za-z0-9_]+)\.([A-Za-z0-9_]*)$/;

/** A name SQL reads as written, without quotes. */
const PLAIN = /^[A-Za-z_][A-Za-z0-9_]*$/;

/** A spreadsheet's name being typed as the first argument of `sheet()`. */
const SPREADSHEET_NAME = /\bsheet\(\s*'((?:[^']|'')*)$/i;

/** What is being completed at *caret*: the word, where it starts, and the name
 *  it is written under if it has one.
 *
 *  `null` where a completion would make no sense — mid-word from the right, or
 *  with nothing typed and nothing to write it under. After a dot there is
 *  something to offer with no word at all, because what may follow one is a
 *  short and closed list. */
export const wordAt = (
  text: string,
  caret: number
): { word: string; start: number; qualifier?: string; quoted?: boolean } | null => {
  // Completing from inside a word would replace only its left half.
  const next = text[caret];
  if (next && WORD.test(next)) return null;
  const before = text.slice(0, caret);
  const named = SPREADSHEET_NAME.exec(before);
  if (named) return { word: named[1], start: caret - named[1].length, quoted: true };
  const qualified = QUALIFIED.exec(before);
  if (qualified) {
    return {
      word: qualified[2],
      start: caret - qualified[2].length,
      qualifier: qualified[1],
    };
  }
  const match = WORD.exec(before);
  if (!match) return null;
  return { word: match[0], start: caret - match[0].length };
};

/** The datasets this statement already names. Word-for-word, so a dataset
 *  mentioned anywhere counts and one that is only a prefix does not. */
export const datasetsNamed = (text: string, datasets: string[]): string[] => {
  const words = new Set(text.toLowerCase().match(/[a-z0-9_]+/g) ?? []);
  return datasets.filter((dataset) => words.has(dataset));
};

/**
 * Everything that could follow *word*, best first.
 *
 * Ordered by how the match was made rather than by kind: a name that starts
 * with what has been typed comes before one that merely contains it, because
 * the first is what somebody typing is reaching for.
 */
export const completionsFor = (
  word: string,
  {
    datasets,
    functions,
    fields,
    tokens = [],
    named = [],
    qualifier,
    ranges = [],
    spreadsheets = [],
    quoted = false,
  }: {
    datasets: string[];
    functions: string[];
    fields: DatasetFields[];
    /** Names resolved from who is asking rather than from the statement. */
    tokens?: string[];
    /** The datasets this statement already names. What may be written bare is
     *  theirs; everything else is reached through one of them. */
    named?: string[];
    /** The name this word is written under, where it has one. */
    qualifier?: string;
    /** The ranges the statement read, each under the name it is read under.
     *  Always in scope: the statement names them. */
    ranges?: DatasetFields[];
    /** The spreadsheets a `sheet()` call may name. */
    spreadsheets?: string[];
    /** Whether the word is a spreadsheet's name inside `sheet('`. */
    quoted?: boolean;
  }
): Completion[] => {
  const needle = word.toLowerCase();
  if (quoted) {
    return spreadsheets
      .filter((name) => matches(name, needle) && name.toLowerCase() !== needle)
      .map((name): Completion => ({ name, kind: "spreadsheet" }));
  }
  const inScope = [
    ...(named.length ? fields.filter((entry) => named.includes(entry.dataset)) : fields),
    ...ranges,
  ];

  // After a dot there is one kind of answer: a column of whatever the name in
  // front resolves to. A dataset resolves to itself; a relation resolves to
  // what it reaches. Nothing else may follow one, so nothing else is offered —
  // and an empty word is enough, because the list is already short.
  if (qualifier !== undefined) {
    return fieldsUnder(qualifier, [...fields, ...ranges], inScope).filter((entry) =>
      matches(entry.name, needle)
    );
  }

  if (!needle) return [];

  const all: Completion[] = [
    ...datasets.map((name): Completion => ({ name, kind: "dataset" })),
    ...inScope.flatMap((entry) =>
      entry.fields.map(
        (field): Completion => ({
          name: field.name,
          kind: "field",
          detail: `${entry.dataset} · ${field.type}`,
        })
      )
    ),
    ...inScope.flatMap((entry) =>
      (entry.relations ?? []).map(
        (relation): Completion => ({
          name: relation.name,
          kind: "relation",
          detail: `${entry.dataset} · ${relation.dataset}`,
        })
      )
    ),
    ...functions.map((name): Completion => ({ name, kind: "function" })),
    ...tokens.map((name): Completion => ({ name, kind: "token" })),
  ];

  const starts: Completion[] = [];
  const contains: Completion[] = [];
  const seen = new Set<string>();
  for (const candidate of all) {
    const key = `${candidate.kind}:${candidate.name}:${candidate.detail ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const name = candidate.name.toLowerCase();
    if (name === needle) continue;
    if (name.startsWith(needle)) starts.push(candidate);
    else if (name.includes(needle)) contains.push(candidate);
  }
  return [...starts, ...contains];
};

/** Whether a name is worth offering for what has been typed so far. */
const matches = (name: string, needle: string): boolean =>
  !needle || name.toLowerCase().includes(needle);

/** The columns a qualifier stands for: a dataset's own, or those of whatever
 *  one of the statement's datasets declares a way to reach under that name.
 *
 *  An alias somebody wrote resolves to neither, and is answered with nothing
 *  rather than with a guess — reading a `FROM` clause properly is the
 *  validator's job, and a second reading of it here is a second thing to keep
 *  right. */
const fieldsUnder = (
  qualifier: string,
  fields: DatasetFields[],
  inScope: DatasetFields[]
): Completion[] => {
  const behind = qualifier.toLowerCase();
  const reached =
    inScope
      .flatMap((entry) => entry.relations ?? [])
      .find((relation) => relation.name.toLowerCase() === behind)?.dataset ?? behind;
  const entry = fields.find((held) => held.dataset.toLowerCase() === reached.toLowerCase());
  return (entry?.fields ?? []).map((field) => ({
    name: field.name,
    kind: "field",
    detail: `${entry?.dataset} · ${field.type}`,
  }));
};

/** The text with *completion* put in place of the word at *start*, and where
 *  the caret lands afterwards. */
export const applyCompletion = (
  text: string,
  start: number,
  end: number,
  completion: Completion
): { text: string; caret: number } => {
  // A relation is never the end of a name: choosing one leaves the caret past
  // the dot, where the next thing offered is one of its columns.
  // A spreadsheet's name closes the quote it was typed in, its own quotes
  // doubled as a string constant's are. A field named by a header SQL cannot
  // read bare (`Q3 total`) goes in double quotes.
  const inserted =
    completion.kind === "function"
      ? `${completion.name}(`
      : completion.kind === "relation"
        ? `${completion.name}.`
        : completion.kind === "spreadsheet"
          ? `${completion.name.replace(/'/g, "''")}'`
          : completion.kind === "field" && !PLAIN.test(completion.name)
            ? `"${completion.name.replace(/"/g, '""')}"`
            : completion.name;
  return {
    text: text.slice(0, start) + inserted + text.slice(end),
    caret: start + inserted.length,
  };
};
