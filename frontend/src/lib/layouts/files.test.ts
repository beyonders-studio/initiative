import { describe, expect, it } from "vitest";

import {
  buildCollectionFile,
  buildPropertyDefinition,
  buildPropertySummary,
} from "@/__tests__/factories";
import { MetadataType } from "@/api/generated/initiativeAPI.schemas";

import type { LayoutItem } from "./fields";
import { cardLines, collectionFileFields } from "./files";
import type { LayoutNode } from "./tree";

const caption = buildPropertyDefinition({ id: 21, name: "Caption", collection_id: 5 });
const price = buildPropertyDefinition({ id: 22, name: "Price", type: MetadataType.currency });
const fields = collectionFileFields([caption], [price]);

const file = buildCollectionFile({
  name: "Harbour",
  metadata: [buildPropertySummary({ property_id: 21, name: "Caption", value: "Dusk" })],
  properties: [buildPropertySummary({ property_id: 22, name: "Price", value: null })],
});
const item = file as unknown as LayoutItem;

const field = (id: string): LayoutNode => ({ type: "field", props: { field: id } });

describe("collectionFileFields", () => {
  it("reads a collection's field from the file's values there, a property from its own", () => {
    expect(fields.get("name")?.value(item)).toBe(file);
    expect(fields.get("property:21")?.value(item)).toMatchObject({ value: "Dusk" });
    // An empty value is no value.
    expect(fields.get("property:22")?.value(item)).toBeNull();
  });
});

describe("cardLines", () => {
  it("counts a line for each field holding a value, and one for a row of them", () => {
    const card: LayoutNode = {
      type: "card",
      children: [
        field("name"),
        field("property:21"),
        field("property:22"),
        { type: "stack", props: { direction: "row" }, children: [field("type"), field("size")] },
      ],
    };
    expect(cardLines(card, item, fields)).toBe(3);
  });

  it("counts a row as tall as its tallest part, properties in it sharing its line", () => {
    const row: LayoutNode = {
      type: "stack",
      props: { direction: "row" },
      children: [
        { type: "properties" },
        { type: "stack", children: [field("name"), field("property:21")] },
      ],
    };
    expect(cardLines(row, { ...item, properties: file.metadata } as LayoutItem, fields)).toBe(2);
  });
});
