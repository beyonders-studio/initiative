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
