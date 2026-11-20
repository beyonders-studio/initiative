import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildPropertyDefinition, buildPropertySummary, buildTask } from "@/__tests__/factories";
import i18n from "@/__tests__/helpers/i18n-test";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { PropertyDefinitionRead, TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { TASK_LAYOUT, taskFields } from "@/lib/layouts/tasks";

/** The page as shipped. */
const TASK_DETAIL = TASK_LAYOUT.tree(undefined);

import type { TranslateFn } from "@/types/i18n";

import { type FieldDef, type LayoutEnv, withDisplays } from "./fields";
import { shippedLists } from "./layoutSet";
import { fieldSorting, presetName, presetsOf, sortedItems, storedPreset } from "./presets";
import {
  LAYOUT_PARTS,
  type LayoutContext,
  type LayoutNode,
  LayoutTree,
  type Parts,
  renderNode,
} from "./tree";

const field = (id: string): LayoutNode => ({ type: "field", props: { field: id } });

const viewOf = (definitions: PropertyDefinitionRead[] = []): LayoutContext<TaskListRead> => ({
  fields: taskFields(definitions),
  variant: "card",
  env: {
    t: i18n.getFixedT(null, ["projects", "dates", "relations"]) as TranslateFn,
    communityPath: (path) => path,
    itemHref: (task) => `/tasks/${task.id}`,
  },
});

const draw = (node: LayoutNode, task: TaskListRead, definitions: PropertyDefinitionRead[] = []) =>
  renderWithProviders(<LayoutTree node={node} item={task} view={viewOf(definitions)} />);

describe("taskFields", () => {
  it("adds one field per property, keyed by its definition id and labelled by name", () => {
    const fields = taskFields([buildPropertyDefinition({ id: 4, name: "Effort" })]);

    expect(fields.get("property:4")).toMatchObject({ label: "Effort", source: "property" });
  });

  it("tells two properties of the same name apart in their labels", () => {
    const fields = taskFields([
      buildPropertyDefinition({ id: 4, name: "Status" }),
      buildPropertyDefinition({ id: 9, name: "Status" }),
    ]);

    expect([...fields.values()].slice(-2).map((field) => field.label)).toEqual([
      "Status (#4)",
      "Status (#9)",
    ]);
  });
});

describe("LayoutTree", () => {
  it("draws nothing for a part or a field it does not know", () => {
    const node: LayoutNode = {
      type: "stack",
      children: [{ type: "nope" }, { type: "constructor" }, field("nope"), field("priority")],
    };

    draw(node, buildTask({ priority: "medium" }));

    expect(screen.getByText(/priority: medium/i)).toBeInTheDocument();
  });

  it("spaces a saved row as one that leaves its gap out, which the server sends as null", () => {
    const row = (props: Record<string, unknown>): LayoutNode => ({
      type: "stack",
      props: { direction: "row", ...props },
      children: [field("priority")],
    });
    const gapOf = (node: LayoutNode) => {
      const { container, unmount } = draw(node, buildTask({ priority: "medium" }));
      const classes = (container.firstElementChild as HTMLElement).className;
      unmount();
      return classes;
    };

    expect(gapOf(row({ gap: null, wrap: null, align: null, tone: null }))).toBe(gapOf(row({})));
    expect(gapOf(row({ gap: null }))).toContain("gap-1");
  });

  it("skips a field with nothing in it", () => {
    const node: LayoutNode = {
      type: "stack",
      children: [field("priority"), field("description"), field("comments"), field("dueDate")],
    };
    const task = buildTask({
      description_excerpt: null,
      comment_count: 0,
      due_date: "2026-08-03T21:15:00Z",
    });

    const { container } = draw(node, { ...task, priority: "medium" });

    expect(container.textContent).toMatch(/^Priority: medium.*Due:/);
  });

  it("draws every property the item has a value for, in its order", () => {
    // One whose definition has not arrived is still drawn.
    const definitions = [
      buildPropertyDefinition({ id: 9, name: "Status" }),
      buildPropertyDefinition({ id: 4, name: "Effort" }),
      buildPropertyDefinition({ id: 12, name: "Status" }),
      buildPropertyDefinition({ id: 15, name: "Owner" }),
    ];
    const task = buildTask({
      properties: [
        buildPropertySummary({ property_id: 4, name: "Effort", value: "large" }),
        buildPropertySummary({ property_id: 15, name: "Owner", value: "" }),
        buildPropertySummary({ property_id: 9, name: "Status", value: "open" }),
        buildPropertySummary({ property_id: 12, name: "Status", value: "shut" }),
        buildPropertySummary({ property_id: 20, name: "Phase", value: "beta" }),
      ],
    });

    const { container } = draw({ type: "properties" }, task, definitions);

    expect(container.textContent).toBe("Effort:largeStatus:openStatus:shutPhase:beta");
  });

  it("draws a property a stored view names by its definition id", () => {
    const task = buildTask({
      properties: [buildPropertySummary({ property_id: 4, name: "Effort", value: "large" })],
    });

    // Another property is named "4": the stored id still names Effort.
    const { container } = draw(field("property:4"), task, [
      buildPropertyDefinition({ id: 4, name: "Effort" }),
      buildPropertyDefinition({ id: 9, name: "4" }),
    ]);

    expect(container.textContent).toBe("Effort:large");
  });
});

describe("renderNode", () => {
  // A detail's view with no fields, for an item of any kind.
  const detailOf = <I,>(): LayoutContext<I> => ({
    fields: new Map(),
    variant: "detail",
    env: {
      t: i18n.getFixedT(null, "projects") as TranslateFn,
      communityPath: (path) => path,
      itemHref: () => "",
    },
  });

  it("draws a detail through the parts it is given", () => {
    // The page's regions are layout any kind of item shares; what fills them
    // is the item's own.
    const parts: Parts<string> = { ...LAYOUT_PARTS, name: (_node, item) => <p>{item}</p> };
    const page: LayoutNode = {
      type: "layout",
      children: [
        { type: "header", children: [{ type: "name" }] },
        { type: "main", children: [{ type: "field", props: { field: "title" } }] },
        { type: "side", children: [{ type: "name" }] },
      ],
    };

    const { container } = renderWithProviders(<>{renderNode(page, "Ada", detailOf(), parts)}</>);

    expect(container.textContent).toBe("AdaAda");
  });

  it("follows a task's description with its fields once its page is one column", () => {
    const named = (name: string) => () => <p>{name}</p>;
    const parts: Parts<null> = {
      ...LAYOUT_PARTS,
      field: (node) => <p>{String(node.props?.field)}</p>,
      status: named("status"),
      dates: named("dates"),
      properties: named("properties"),
      case: named("case"),
      relations: named("relations"),
      comments: named("comments"),
    };

    const { container } = renderWithProviders(
      <>{renderNode(TASK_DETAIL, null, detailOf(), parts)}</>
    );

    // Each part of a column carries where it falls on the one column.
    const stacked = [...container.querySelectorAll("div")]
      .map((part) => ({ order: /(?:^|\s)order-(\d+)/.exec(part.className)?.[1], part }))
      .filter((entry) => entry.order !== undefined)
      .sort((a, b) => Number(a.order) - Number(b.order))
      .map(({ part }) => part.querySelector("p")?.textContent);
    expect(stacked).toEqual(["description", "type", "checklist", "case", "relations", "comments"]);
  });
});

describe("a task detail's tree", () => {
  const regions = (tree: LayoutNode) =>
    Object.fromEntries((tree.children ?? []).map((region) => [region.type, region.children]));

  it("draws what a layout stores, the rest as shipped, and nothing it leaves out", () => {
    const work: LayoutNode = {
      type: "section",
      props: { title: "Work" },
      children: [field("description")],
    };

    const page = regions(TASK_LAYOUT.tree({ main: [work], side: [] }));

    expect(page.header).toEqual(regions(TASK_DETAIL).header);
    // Drawn where the shipped page puts what it starts with on one column.
    expect(page.main).toEqual([{ ...work, props: { ...work.props, order: 1 } }]);
    expect(page.side).toEqual([]);
  });
});

/** A row of a laid-out table, as a tool plug-in's: its fields by key, and
 *  the items under it. */
type Row = {
  properties: [];
  values: Record<string, unknown>;
  counters?: Row[];
};

const row = (values: Record<string, unknown>, counters?: Row[]): Row => ({
  properties: [],
  values,
  counters,
});

/** Each of `keys` a field drawing its value as text. */
const fieldsOf = (...keys: string[]): ReadonlyMap<string, FieldDef<Row>> =>
  new Map(
    keys.map((key) => [
      key,
      {
        id: key,
        source: "builtin",
        label: key,
        hideable: true,
        requireable: false,
        value: (item: Row) => item.values[key],
        render: ({ value }) => <span>{String(value)}</span>,
      } satisfies FieldDef<Row>,
    ])
  );

const env = (extra: Partial<LayoutEnv<Row>> = {}): LayoutEnv<Row> => ({
  t: i18n.getFixedT(null, "layouts") as TranslateFn,
  communityPath: (path) => path,
  itemHref: () => "/row",
  ...extra,
});

const drawRow = (node: LayoutNode, item: Row, view: Partial<LayoutContext<Row>> = {}) =>
  renderWithProviders(
    <LayoutTree
      node={node}
      item={item}
      view={{ fields: fieldsOf("name", "color"), variant: "card", env: env(), ...view }}
    />
  );

describe("a tool plug-in's card", () => {
  it("is drawn in the colour its tint field holds, and plain without one", () => {
    const card: LayoutNode = { type: "card", props: { tint: "color" }, children: [field("name")] };

    const { unmount } = drawRow(card, row({ name: "Tinted", color: "#5B7FC2" }));
    expect(screen.getByText("Tinted").parentElement).toHaveStyle({
      backgroundColor: "#5B7FC2",
      color: "#FFFFFF",
    });
    unmount();

    drawRow(card, row({ name: "Plain", color: "blue" }));
    expect(screen.getByText("Plain").parentElement).not.toHaveAttribute("style");
  });

  it("previews the row's first items, each line in its own colour", () => {
    const items = fieldsOf("name", "count", "color");
    const preview: LayoutNode = {
      type: "items",
      props: { item: "counter", fields: ["name", "count"], limit: 2, tint: "color" },
    };
    const group = row({ name: "Group" }, [
      row({ name: "Gold", count: 3, color: "#C2A35B" }),
      row({ name: "Silver", count: 5 }),
      row({ name: "Bronze", count: 8 }),
    ]);
    const itemPreview: LayoutEnv<Row>["itemPreview"] = (item, table, limit) =>
      table === "counter"
        ? { items: (item.counters ?? []).slice(0, limit), fields: items, env: env() as LayoutEnv }
        : null;

    drawRow(preview, group, { env: env({ itemPreview }) });

    const lines = screen.getAllByRole("listitem");
    expect(lines.map((line) => line.textContent)).toEqual(["Gold3", "Silver5"]);
    expect(lines[0]).toHaveStyle({ backgroundColor: "#C2A35B" });
    expect(lines[1]).not.toHaveAttribute("style");
  });

  it("previews nothing where the list cannot read a row's items", () => {
    const preview: LayoutNode = {
      type: "items",
      props: { item: "counter", fields: ["name"], limit: 4 },
    };

    drawRow(preview, row({ name: "Group" }, [row({ name: "Gold" })]));

    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });
});

describe("withDisplays", () => {
  it("draws a field in the look each row's select field names", () => {
    const fields = withDisplays(fieldsOf("count", "view_mode", "mood"), {
      count: { from: "view_mode" },
      mood: "stars",
    });
    const count = fields.get("count");

    expect(count?.displayOf?.(row({ view_mode: "clock" }))).toBe("clock");
    expect(count?.displayOf?.(row({ view_mode: { value: "bar" } }))).toBe("bar");
    expect(count?.displayOf?.(row({}))).toBeUndefined();
    expect(fields.get("mood")?.display).toBe("stars");
  });
});

describe("a tool plug-in's presets", () => {
  const kind = { shipped: [], read: () => ({}), sorting: fieldSorting };
  const definition = {
    presets: [
      {
        slug: "by-count",
        name: { en: "By count", de: "Nach Zählung" },
        sort: [{ field: "count", dir: "desc" as const }, { field: "name" }],
      },
    ],
  };
  const t = (key: string) => key;

  it("are named in the reader's language, else in English", () => {
    const [preset] = presetsOf(definition, kind);

    expect(presetName(preset, t, "de-CH")).toBe("Nach Zählung");
    expect(presetName(preset, t, "fr")).toBe("By count");
  });

  it("keep their names and sort as the layout keeps them", () => {
    const [preset] = presetsOf(definition, kind);

    expect(preset.sorting).toEqual([
      { id: "count", desc: true },
      { id: "name", desc: false },
    ]);
    expect(storedPreset(preset, kind)).toMatchObject({
      name: definition.presets[0].name,
      slug: "by-count",
      sort: [
        { field: "count", dir: "desc" },
        { field: "name", dir: "asc" },
      ],
    });
  });

  it("sort what is shown and leave the rows' own order alone", () => {
    const rows = [
      row({ name: "b", count: 2 }),
      row({ name: "a", count: null }),
      row({ name: "c", count: 2 }),
      row({ name: "d", count: 10 }),
    ];
    const order = rows.map((each) => each.values.name);

    const sorted = sortedItems(
      rows,
      [
        { id: "count", desc: true },
        { id: "name", desc: true },
      ],
      fieldsOf("name", "count")
    );

    expect(sorted.map((each) => each.values.name)).toEqual(["d", "c", "b", "a"]);
    expect(rows.map((each) => each.values.name)).toEqual(order);
  });
});

describe("shippedLists", () => {
  it("offers each declared list, the first the one a person starts on", () => {
    const views = shippedLists([
      { kind: "grid", card: { type: "card", children: [] } },
      { kind: "table", columns: ["name"] },
    ]);

    expect(views.map((view) => [view.kind, view.is_default])).toEqual([
      ["grid", true],
      ["table", false],
    ]);
    expect(views[1].definition).toEqual({ columns: ["name"] });
  });
});
