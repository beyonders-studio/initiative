import { describe, expect, it } from "vitest";

import {
  applyCompletion,
  completionsFor,
  type DatasetFields,
  datasetsNamed,
  type PluginReads,
  wordAt,
} from "@/lib/widgets/completion";

const DATASETS = ["tasks", "projects", "calendar_events"];
const FUNCTIONS = ["count", "date_trunc", "lower"];
const FIELDS: DatasetFields[] = [
  {
    dataset: "tasks",
    fields: [
      { name: "title", type: "text" },
      { name: "due_date", type: "date" },
      { name: "priority", type: "enum" },
    ],
  },
  {
    dataset: "projects",
    fields: [
      { name: "name", type: "text" },
      { name: "start_date", type: "date" },
    ],
  },
];

const vocabulary = { datasets: DATASETS, functions: FUNCTIONS, fields: FIELDS };

/** A catalog whose tasks reach people, the way the registry declares it. */
const REACHING: DatasetFields[] = [
  {
    dataset: "tasks",
    fields: [
      { name: "title", type: "text" },
      { name: "priority", type: "enum" },
    ],
    relations: [
      { name: "assignee", dataset: "members" },
      { name: "project", dataset: "projects" },
    ],
  },
  {
    dataset: "members",
    fields: [
      { name: "display_name", type: "text" },
      { name: "username", type: "text" },
    ],
  },
  { dataset: "projects", fields: [{ name: "name", type: "text" }] },
];

const reaching = {
  datasets: ["tasks", "members", "projects"],
  functions: FUNCTIONS,
  fields: REACHING,
};

describe("the word being typed", () => {
  it("is what precedes the caret", () => {
    expect(wordAt("SELECT ti", 9)).toEqual({ word: "ti", start: 7 });
  });

  it("is nothing where a name could not go", () => {
    expect(wordAt("SELECT ", 7)).toBeNull();
    expect(wordAt("", 0)).toBeNull();
  });

  it("is nothing from inside a word", () => {
    // Completing here would replace only the left half of `title`.
    expect(wordAt("SELECT title", 9)).toBeNull();
  });

  it("stops at what a name cannot contain", () => {
    expect(wordAt("count(ti", 8)).toEqual({ word: "ti", start: 6 });
  });

  it("reads the name a word is written under", () => {
    expect(wordAt("WHERE t.pri", 11)).toEqual({ word: "pri", start: 8, qualifier: "t" });
  });

  it("is a name and no word at all, straight after a dot", () => {
    // What may follow one is short and closed, so there is something to offer
    // before anything is typed.
    expect(wordAt("SELECT assignee.", 16)).toEqual({
      word: "",
      start: 16,
      qualifier: "assignee",
    });
  });
});

describe("what is offered", () => {
  it("is nothing until something is typed", () => {
    expect(completionsFor("", vocabulary)).toEqual([]);
  });

  it("leads with what starts with the word", () => {
    const names = completionsFor("da", vocabulary).map((entry) => entry.name);
    // `date_trunc` starts with it; `due_date` and `start_date` only contain it.
    expect(names[0]).toBe("date_trunc");
    expect(names).toContain("due_date");
    expect(names.indexOf("date_trunc")).toBeLessThan(names.indexOf("due_date"));
  });

  it("offers datasets, fields and functions together", () => {
    const kinds = new Set(completionsFor("t", vocabulary).map((entry) => entry.kind));
    expect(kinds).toEqual(new Set(["dataset", "field", "function"]));
  });

  it("offers the reader beside them", () => {
    const found = completionsFor("m", { ...vocabulary, tokens: ["me"] });
    expect(found).toContainEqual({ name: "me", kind: "token" });
  });

  it("offers no token where the server names none", () => {
    const kinds = completionsFor("m", vocabulary).map((entry) => entry.kind);
    expect(kinds).not.toContain("token");
  });

  it("says where a field comes from", () => {
    const found = completionsFor("priority", vocabulary)[0];
    expect(found).toBeUndefined();
    const partial = completionsFor("prior", vocabulary)[0];
    expect(partial).toMatchObject({ name: "priority", kind: "field", detail: "tasks · enum" });
  });

  it("does not offer the word already written in full", () => {
    expect(completionsFor("tasks", vocabulary).map((entry) => entry.name)).not.toContain("tasks");
  });

  it("is case-insensitive", () => {
    expect(completionsFor("TI", vocabulary).map((entry) => entry.name)).toContain("title");
  });

  it("offers the same field once per dataset that has it", () => {
    const shared: DatasetFields[] = [
      { dataset: "tasks", fields: [{ name: "created_at", type: "date" }] },
      { dataset: "projects", fields: [{ name: "created_at", type: "date" }] },
    ];
    const found = completionsFor("created", { ...vocabulary, fields: shared });
    expect(found).toHaveLength(2);
    expect(found.map((entry) => entry.detail)).toEqual(["tasks · date", "projects · date"]);
  });
});

describe("the datasets a statement names", () => {
  it("are the ones written as whole words", () => {
    expect(datasetsNamed("SELECT title FROM tasks", DATASETS)).toEqual(["tasks"]);
  });

  it("do not include one that is only a prefix of a word", () => {
    expect(datasetsNamed("SELECT task_status_id FROM x", DATASETS)).toEqual([]);
  });

  it("include every one a join names", () => {
    expect(
      datasetsNamed("SELECT p.name FROM projects p JOIN tasks t ON t.project_id = p.id", DATASETS)
    ).toEqual(["tasks", "projects"]);
  });
});

describe("accepting one", () => {
  it("replaces the word being typed", () => {
    expect(applyCompletion("SELECT ti", 7, 9, { name: "title", kind: "field" })).toEqual({
      text: "SELECT title",
      caret: 12,
    });
  });

  it("opens the bracket on a function", () => {
    expect(applyCompletion("SELECT co", 7, 9, { name: "count", kind: "function" })).toEqual({
      text: "SELECT count(",
      caret: 13,
    });
  });

  it("keeps what follows the caret", () => {
    expect(applyCompletion("SELECT ti FROM tasks", 7, 9, { name: "title", kind: "field" })).toEqual(
      { text: "SELECT title FROM tasks", caret: 12 }
    );
  });
});

describe("reaching through a relation", () => {
  const named = ["tasks"];

  it("offers what the statement's dataset can be read alongside", () => {
    const found = completionsFor("assi", { ...reaching, named });
    expect(found).toContainEqual({
      name: "assignee",
      kind: "relation",
      detail: "tasks · members",
    });
  });

  it("offers a related dataset's columns under the relation's name", () => {
    const names = completionsFor("disp", {
      ...reaching,
      named,
      qualifier: "assignee",
    }).map((entry) => entry.name);
    expect(names).toEqual(["display_name"]);
  });

  it("offers all of them where nothing is typed yet", () => {
    const names = completionsFor("", { ...reaching, named, qualifier: "assignee" }).map(
      (entry) => entry.name
    );
    expect(names).toEqual(["display_name", "username"]);
  });

  it("offers a dataset's own columns where the dataset is what qualifies", () => {
    const names = completionsFor("", { ...reaching, named, qualifier: "tasks" }).map(
      (entry) => entry.name
    );
    expect(names).toEqual(["title", "priority"]);
  });

  it("offers nothing under a name that reaches nothing", () => {
    // An alias somebody wrote. Reading a FROM clause properly is the
    // validator's job, and a guess here would offer columns that are not there.
    expect(completionsFor("", { ...reaching, named, qualifier: "t" })).toEqual([]);
  });

  it("offers nothing but columns after a dot", () => {
    const kinds = completionsFor("", { ...reaching, named, qualifier: "assignee" }).map(
      (entry) => entry.kind
    );
    expect(new Set(kinds)).toEqual(new Set(["field"]));
  });

  it("keeps a bare name to what the statement itself names", () => {
    // `display_name` is reachable, not nameable: it needs its relation in front.
    const names = completionsFor("name", { ...reaching, named }).map((entry) => entry.name);
    expect(names).not.toContain("display_name");
  });

  it("puts the dot in for you when a relation is chosen", () => {
    const applied = applyCompletion("SELECT assi", 7, 11, {
      name: "assignee",
      kind: "relation",
    });
    expect(applied.text).toBe("SELECT assignee.");
    expect(applied.caret).toBe(16);
  });
});

describe("reading a spreadsheet", () => {
  const RANGE: DatasetFields = {
    dataset: "b",
    fields: [
      { name: "Region", type: "text" },
      { name: "Amount", type: "number" },
    ],
  };

  it("offers the spreadsheets by name inside the quote that opens one", () => {
    const text = "SELECT x FROM sheet('Bu";
    const found = wordAt(text, text.length);
    expect(found).toEqual({ word: "Bu", start: text.length - 2, quoted: "spreadsheet" });
    const offered = completionsFor(found?.word ?? "", {
      ...vocabulary,
      spreadsheets: ["Budget", "Q3 Budget", "Roster"],
      quoted: "spreadsheet",
    });
    expect(offered.map((entry) => entry.name)).toEqual(["Budget", "Q3 Budget"]);
    expect(applyCompletion(text, found?.start ?? 0, text.length, offered[1]).text).toBe(
      "SELECT x FROM sheet('Q3 Budget'"
    );
    expect(applyCompletion("sheet('", 7, 7, { name: "Jo's sheet", kind: "spreadsheet" }).text).toBe(
      "sheet('Jo''s sheet'"
    );
    expect(applyCompletion("SELECT sum(q", 11, 12, { name: "Q3 total", kind: "field" }).text).toBe(
      'SELECT sum("Q3 total"'
    );
  });

  it("offers a range's columns bare and under the name it is read under", () => {
    const named = datasetsNamed("SELECT re FROM tasks", DATASETS);
    expect(
      completionsFor("re", { ...vocabulary, named, ranges: [RANGE] }).map((entry) => entry.name)
    ).toContain("Region");
    expect(
      completionsFor("", { ...vocabulary, qualifier: "b", ranges: [RANGE] }).map(
        (entry) => entry.name
      )
    ).toEqual(["Region", "Amount"]);
  });
});

describe("reading a plug-in", () => {
  const PLUGINS: PluginReads[] = [
    {
      publicId: "acme.shop",
      endpoints: [
        { name: "orders", params: [{ key: "range" }, { key: "tags" }] },
        { name: "refunds" },
      ],
    },
    { publicId: "acme.crm", endpoints: [{ name: "leads" }] },
  ];

  /** What is offered with the caret at the end of *text*, and *text* with the
   *  first of them chosen. */
  const offer = (text: string) => {
    const found = wordAt(text, text.length);
    const offered = completionsFor(found?.word ?? "", {
      ...vocabulary,
      plugins: PLUGINS,
      quoted: found?.quoted,
      call: found?.call,
    });
    return {
      found,
      names: offered.map((entry) => entry.name),
      chosen: offered[0]
        ? applyCompletion(text, found?.start ?? 0, text.length, offered[0]).text
        : undefined,
    };
  };

  it("offers plugin( where a relation goes", () => {
    const found = completionsFor("plu", { ...vocabulary, functions: [...FUNCTIONS, "plugin"] });
    expect(found).toContainEqual({ name: "plugin", kind: "function" });
    expect(applyCompletion("FROM plu", 5, 8, found[0]).text).toBe("FROM plugin(");
  });

  it("offers the installed plug-ins by id inside the first quote", () => {
    const text = "SELECT * FROM plugin('acme.";
    const { found, names, chosen } = offer(text);
    expect(found).toEqual({ word: "acme.", start: text.length - 5, quoted: "plugin" });
    expect(names).toEqual(["acme.shop", "acme.crm"]);
    expect(chosen).toBe("SELECT * FROM plugin('acme.shop'");
  });

  it("offers that plug-in's endpoints by name inside the second", () => {
    const { names, chosen } = offer("FROM plugin('acme.shop', '");
    expect(names).toEqual(["orders", "refunds"]);
    expect(chosen).toBe("FROM plugin('acme.shop', 'orders'");
    expect(offer("FROM plugin('acme.crm', 'l").names).toEqual(["leads"]);
  });

  it("offers the endpoint's parameters by name after both", () => {
    const { names, chosen } = offer("FROM plugin('acme.shop', 'orders', ");
    expect(names).toEqual(["range", "tags"]);
    expect(chosen).toBe("FROM plugin('acme.shop', 'orders', range => ");
    expect(offer("FROM plugin('acme.shop', 'orders', range => '30d', ta").names).toEqual(["tags"]);
  });

  it("offers no parameter inside a value, or once the call is closed", () => {
    expect(offer("FROM plugin('acme.shop', 'orders', tags => ARRAY['a', ").found).toBeNull();
    expect(offer("FROM plugin('acme.shop', 'orders', range => ").found).toBeNull();
    expect(offer("FROM plugin('acme.shop', 'orders') AS o, ta").found).toEqual({
      word: "ta",
      start: 41,
    });
  });

  it("offers nothing for a plug-in or an endpoint it does not know", () => {
    expect(offer("FROM plugin('acme.nope', '").names).toEqual([]);
    expect(offer("FROM plugin('acme.shop', 'nope', ").names).toEqual([]);
  });

  it("offers an endpoint's columns under the name it is read under", () => {
    const read: DatasetFields = {
      dataset: "o",
      fields: [
        { name: "status", type: "text" },
        { name: "total", type: "number" },
      ],
    };
    expect(
      completionsFor("", { ...vocabulary, qualifier: "o", ranges: [read] }).map(
        (entry) => entry.name
      )
    ).toEqual(["status", "total"]);
  });
});
