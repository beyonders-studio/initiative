import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import i18n from "@/__tests__/helpers/i18n-test";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { TranslateFn } from "@/types/i18n";

import { type FieldDef, type LayoutEnv, withDisplays } from "./fields";
import { shippedLists } from "./layoutSet";
import { fieldSorting, presetName, presetsOf, sortedItems, storedPreset } from "./presets";
import { type LayoutContext, type LayoutNode, LayoutTree } from "./tree";

/** A row of a tool plug-in's table: its fields by key, and the items under
 *  it. */
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

const draw = (node: LayoutNode, item: Row, view: Partial<LayoutContext<Row>> = {}) =>
  renderWithProviders(
    <LayoutTree
      node={node}
      item={item}
      view={{ fields: fieldsOf("name", "color"), variant: "card", env: env(), ...view }}
    />
  );

const field = (key: string): LayoutNode => ({ type: "field", props: { field: key } });

describe("a tool plug-in's card", () => {
  it("is drawn in the colour its tint field holds, and plain without one", () => {
    const card: LayoutNode = { type: "card", props: { tint: "color" }, children: [field("name")] };

    const { unmount } = draw(card, row({ name: "Tinted", color: "#5B7FC2" }));
    expect(screen.getByText("Tinted").parentElement).toHaveStyle({
      backgroundColor: "#5B7FC2",
      color: "#FFFFFF",
    });
    unmount();

    draw(card, row({ name: "Plain", color: "blue" }));
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

    draw(preview, group, { env: env({ itemPreview }) });

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

    draw(preview, row({ name: "Group" }, [row({ name: "Gold" })]));

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
