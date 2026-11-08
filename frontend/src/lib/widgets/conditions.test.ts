import { describe, expect, it } from "vitest";

import type { FieldDescription } from "@/api/generated/initiativeAPI.schemas";
import {
  countLeaves,
  expandConditions,
  type FilterNode,
  fieldSpec,
  isGroup,
  toFilterFieldSpec,
} from "@/lib/widgets/conditions";

const DAY = 86_400_000;
const NOW = Date.UTC(2026, 7, 3);

describe("countLeaves", () => {
  it("counts comparisons through groups, not top-level entries", () => {
    const nodes: FilterNode[] = [
      { field: "priority", op: "in_", value: ["high"] },
      {
        logic: "or",
        conditions: [
          { field: "title", op: "ilike", value: "a" },
          { field: "title", op: "ilike", value: "b" },
        ],
      },
    ];
    expect(countLeaves(nodes)).toBe(3);
  });
});

describe("expandConditions", () => {
  it("resolves a relative date against the given instant", () => {
    const nodes: FilterNode[] = [{ field: "due_date", op: "lt", value: { relative: 30 } }];
    const [leaf] = expandConditions(nodes, NOW);
    expect(leaf).toEqual({
      field: "due_date",
      op: "lt",
      value: new Date(NOW + 30 * DAY).toISOString(),
    });
  });

  it("resolves negative offsets as the past", () => {
    const nodes: FilterNode[] = [{ field: "created_at", op: "gte", value: { relative: -7 } }];
    const [leaf] = expandConditions(nodes, NOW);
    expect(leaf).toHaveProperty("value", new Date(NOW - 7 * DAY).toISOString());
  });

  it("leaves an absolute date alone", () => {
    const nodes: FilterNode[] = [{ field: "due_date", op: "lt", value: "2026-09-30T00:00:00Z" }];
    expect(expandConditions(nodes, NOW)).toEqual(nodes);
  });

  it("reaches relative dates inside a group", () => {
    const nodes: FilterNode[] = [
      { logic: "or", conditions: [{ field: "due_date", op: "lt", value: { relative: 1 } }] },
    ];
    const [group] = expandConditions(nodes, NOW);
    expect(isGroup(group) && group.conditions[0]).toHaveProperty(
      "value",
      new Date(NOW + DAY).toISOString()
    );
  });

  it("moves with the clock, so a saved question does not freeze on its save date", () => {
    const nodes: FilterNode[] = [{ field: "due_date", op: "lt", value: { relative: 30 } }];
    const [first] = expandConditions(nodes, NOW);
    const [later] = expandConditions(nodes, NOW + 10 * DAY);
    expect(first).not.toEqual(later);
  });
});

describe("reading the server's field declarations", () => {
  // The list itself is the server's now; what is tested here is the mapping
  // onto the shape the controls read, and the lookup over it.
  const described: FieldDescription[] = [
    {
      name: "assignee_ids",
      type: "reference",
      kind: "member",
      ops: ["in_", "is_null"],
      multiple: true,
      sortable: false,
    },
    {
      name: "due_date",
      type: "date",
      kind: "date",
      ops: ["lt", "gte"],
      multiple: false,
      sortable: true,
    },
  ];

  it("maps a description onto the shape a control reads", () => {
    const spec = toFilterFieldSpec(described[0]);
    expect(spec).toEqual({
      field: "assignee_ids",
      kind: "member",
      ops: ["in_", "is_null"],
      multiple: true,
    });
  });

  it("passes the operators through untouched", () => {
    // Kinds and operators are the server's own enums, reaching this build
    // through the generated client — so there is nothing to translate and no
    // value that could be one this client does not know.
    const spec = toFilterFieldSpec(described[1]);
    expect(spec.ops).toBe(described[1].ops);
  });

  it("resolves a known field and returns nothing for an unknown one", () => {
    const fields = described.map(toFilterFieldSpec);
    expect(fieldSpec(fields, "assignee_ids")?.kind).toBe("member");
    expect(fieldSpec(fields, "not_a_field")).toBeUndefined();
  });
});
