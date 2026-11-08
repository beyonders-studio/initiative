/**
 * What a collection's lists show of each file: the file's own fields, the
 * collection's metadata and the initiative's properties, drawn through the
 * same fields, cards and columns a project's lists draw tasks with.
 */

import { memo } from "react";

import type {
  CollectionFileSummary,
  FileSummary,
  PropertyDefinitionRead,
} from "@/api/generated/initiativeAPI.schemas";
import { FileTypeBadge } from "@/components/files/fileColumns";
import { at, detailLayoutSpec, type Region } from "@/ui/layouts/detailLayout";
import type { ListShape } from "@/ui/layouts/draft";
import {
  type FieldDef,
  type FieldRendererProps,
  isEmptyValue,
  type LayoutItem,
  propertyFields,
} from "@/ui/layouts/fields";
import type { LayoutNode } from "@/ui/layouts/tree";
import { formatBytes } from "@/ui/lib/fileUtils";
import { cn } from "@/ui/lib/utils";
import { listedValue, nonEmptyPropertySummaries } from "@/ui/properties/propertyHelpers";

/** The file a collection's list draws, which its fields are read from. */
const fileOf = (item: LayoutItem) => item as unknown as CollectionFileSummary;

// A file's own fields hold the file, or its size, as their value.
const NameField = memo(function NameField({ value, variant }: FieldRendererProps) {
  return (
    <p className={cn("min-w-0 truncate", variant === "card" ? "font-medium text-sm" : "text-sm")}>
      {(value as FileSummary).name}
    </p>
  );
});

const TypeField = memo(function TypeField({ value }: FieldRendererProps) {
  return <FileTypeBadge file={value as FileSummary} />;
});

// A file of the app's own has no size; a cell says so.
const SizeField = memo(function SizeField({ value, variant }: FieldRendererProps) {
  return typeof value === "number" ? (
    <span
      className={cn(
        "tabular-nums",
        variant === "card" ? "text-muted-foreground text-xs" : "text-sm"
      )}
    >
      {formatBytes(value)}
    </span>
  ) : variant === "cell" ? (
    <span className="text-muted-foreground text-sm">&mdash;</span>
  ) : null;
});

/** A file's own fields, by the id a layout names each by (`FileFieldId`). */
const FILE_FIELDS: Record<
  string,
  Pick<FieldDef, "kind" | "render" | "label" | "phrase"> & {
    read: (file: CollectionFileSummary) => unknown;
  }
> = {
  name: { render: NameField, label: "common:name", read: (file) => file },
  type: { render: TypeField, label: "files:columns.type", read: (file) => file },
  size: { render: SizeField, label: "files:columns.size", read: (file) => file.file_size },
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

const field = (id: string): LayoutNode => ({ type: "field", props: { field: id } });

/** A file opened from a collection as shipped: its name, then the
 *  collection's metadata and the properties it holds. */
const FILE_DETAIL_REGIONS: Record<Region, LayoutNode[]> = {
  header: [field("name")],
  main: [at(1, { type: "section", children: [{ type: "properties" }] })],
  side: [],
};

/** A file opened from a collection: its own fields, which it does not edit,
 *  can be placed beside the collection's metadata and the initiative's
 *  properties. */
export const FILE_LAYOUT = detailLayoutSpec({
  kind: "file",
  shipped: FILE_DETAIL_REGIONS,
  fieldParts: ["field", "properties"],
  requiredParts: [],
  knows: {
    ...FILE_DETAIL_REGIONS,
    side: Object.keys(FILE_FIELDS)
      .filter((id) => id !== "name")
      .map(field),
  },
});

/**
 * Everything a collection's list can show of a file: its own fields, then the
 * collection's metadata (its values in the collection's list), then the
 * initiative's properties (its own values). Two that share a name are told
 * apart in their labels, as properties are.
 */
export const collectionFileFields = (
  metadata: PropertyDefinitionRead[],
  properties: PropertyDefinitionRead[]
): Map<string, FieldDef> => {
  const own = new Set(metadata.map((definition) => definition.id));
  const fields: FieldDef[] = [
    ...Object.entries(FILE_FIELDS).map(
      ([id, { read, ...field }]): FieldDef => ({
        id,
        source: "builtin",
        hideable: true,
        // A file's own fields are its, and nobody fills them in here.
        requireable: false,
        value: (item) => read(fileOf(item)),
        ...field,
      })
    ),
    ...propertyFields([...metadata, ...properties], (item, definition) => {
      const file = fileOf(item);
      return listedValue(own.has(definition.id) ? file.metadata : file.properties, definition);
    }).map((field) => ({
      ...field,
      plain: true,
      // A collection requires its own metadata, not what the file holds.
      requireable: field.requireable && own.has(Number(field.property?.id)),
    })),
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
