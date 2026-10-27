/**
 * What a collection's lists show of each file: the file's own fields, the
 * collection's fields and the initiative's properties, drawn through the same
 * fields, cards and columns a project's lists draw tasks with.
 */

import type {
  CollectionFileSummary,
  PropertyDefinitionRead,
  PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";
import {
  isEmptyPropertyValue,
  nonEmptyPropertySummaries,
} from "@/components/properties/propertyHelpers";

import type { ListShape } from "./draft";
import { type FieldDef, type FieldKind, isEmptyValue, type LayoutItem } from "./fields";
import { propertyFields } from "./tasks";
import type { LayoutNode } from "./tree";

/** The file a collection's list draws, which its fields are read from. */
const fileOf = (item: LayoutItem) => item as unknown as CollectionFileSummary;

/** A file's own fields, by the id a layout names each by (`FileFieldId`). */
const FILE_FIELDS: Record<
  string,
  {
    kind: FieldKind;
    label: string;
    phrase?: string;
    read: (file: CollectionFileSummary) => unknown;
  }
> = {
  name: { kind: "fileName", label: "common:name", read: (file) => file },
  type: { kind: "fileType", label: "files:columns.type", read: (file) => file },
  size: { kind: "fileSize", label: "files:columns.size", read: (file) => file.file_size },
  added: {
    kind: "date",
    label: "files:columns.added",
    phrase: "files:collections.addedOn",
    read: (file) => file.added_at,
  },
  created: {
    kind: "date",
    label: "files:columns.created",
    phrase: "files:collections.createdOn",
    read: (file) => file.created_at,
  },
};

/** The table column each of a file's own fields is, where its id is not the
 *  field's: what the server sorts the list by. */
export const FILE_COLUMN_OF: Readonly<Record<string, string>> = {
  added: "added_at",
  created: "created_at",
};

/** A collection's lists until they are changed: a card of the picture alone,
 *  and a table of each file's name, type, size and when it was added. */
export const FILE_LIST_SHAPE: ListShape = {
  card: { type: "card", children: [] } satisfies LayoutNode,
  columns: ["name", "type", "size", "added"],
  columnFields: new Set(Object.keys(FILE_FIELDS)),
};

const heldValue = (summaries: PropertySummary[] | undefined, id: number) => {
  const summary = summaries?.find((each) => each.property_id === id);
  return summary && !isEmptyPropertyValue(summary.value) ? summary : null;
};

/**
 * Everything a collection's list can show of a file: its own fields, then the
 * collection's (its values in the collection's list), then the initiative's
 * properties (its own values). Two that share a name are told apart in their
 * labels, as properties are.
 */
export const collectionFileFields = (
  collectionFields: PropertyDefinitionRead[],
  properties: PropertyDefinitionRead[]
): Map<string, FieldDef> => {
  const own = new Set(collectionFields.map((definition) => definition.id));
  const fields: FieldDef[] = [
    ...Object.entries(FILE_FIELDS).map(
      ([id, { read, ...field }]): FieldDef => ({
        id,
        source: "builtin",
        hideable: true,
        value: (item) => read(fileOf(item)),
        ...field,
      })
    ),
    ...propertyFields([...collectionFields, ...properties], (item, id) => {
      const file = fileOf(item);
      return heldValue(own.has(id) ? file.fields : file.properties, id);
    }).map((field) => ({ ...field, plain: true })),
  ];
  return new Map(fields.map((field) => [field.id, field]));
};

/**
 * How many lines a card draws under a file's picture, which draws each field
 * and row on one line: one for each field it shows a value of, one for each
 * property where it shows them all, and a row as many as its tallest part
 * (properties in a row share its line). What a wall that places files without
 * measuring them reserves for the card.
 */
export const cardLines = (
  node: LayoutNode,
  item: LayoutItem,
  fields: ReadonlyMap<string, FieldDef>,
  inRow = false
): number => {
  switch (node.type) {
    case "field": {
      const field = fields.get(String(node.props?.field));
      return field && !isEmptyValue(field.value(item)) ? 1 : 0;
    }
    case "properties": {
      const count = nonEmptyPropertySummaries(item.properties).length;
      return inRow ? Math.min(1, count) : count;
    }
    default: {
      const row = node.type === "stack" && node.props?.direction === "row";
      const lines = (node.children ?? []).map((child) => cardLines(child, item, fields, row));
      return row ? Math.max(0, ...lines) : lines.reduce((sum, each) => sum + each, 0);
    }
  }
};
