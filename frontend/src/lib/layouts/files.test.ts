import { describe, expect, it } from "vitest";

import {
  buildCollectionFile,
  buildPropertyDefinition,
  buildPropertySummary,
} from "@/__tests__/factories";
import { MetadataType } from "@/api/generated/initiativeAPI.schemas";
import type { LayoutItem } from "@/ui/layouts/fields";
import type { LayoutNode } from "@/ui/layouts/tree";

import { cardLines, collectionFileFields } from "./files";

const caption = buildPropertyDefinition({ id: 21, name: "Caption", collection_id: 5 });
const price = buildPropertyDefinition({ id: 22, name: "Price", type: MetadataType.currency });
const stock = buildPropertyDefinition({
  id: 23,
  name: "Stock",
  type: MetadataType.counter,
  counter: { step: 1, min: 0, max: null, initial: 4 },
});
const fields = collectionFileFields([caption], [price, stock]);

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
    // An empty value is no value, but a counter the file has never held
    // holds its initial value.
    expect(fields.get("property:22")?.value(item)).toBeNull();
    expect(fields.get("property:23")?.value(item)).toMatchObject({
      property_id: 23,
      value: null,
      counter: { initial: 4 },
    });
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
