import type { AppColumnDef } from "@/ui/lib/table";
import { PropertyColumnHeader } from "@/ui/properties/propertyColumns";
import { SortHeader } from "@/ui/sort-icon";

import { type FieldDef, fieldRenderer, type LayoutEnv, type LayoutItem } from "./fields";

export type FieldColumnOptions<T extends LayoutItem> = Pick<
  AppColumnDef<T>,
  "sortFn" | "sortUndefined" | "size" | "cell"
> & {
  /** The column's id, where not the field's: what a kind's table keys it by. */
  id?: string;
  /** What the column sorts by, where that is not the field's value. */
  sortBy?: (item: T) => unknown;
};

/**
 * A field as a table column: the field's id, its label as the header, and its
 * renderer's cell. It sorts only when given a `sortFn`.
 */
export const fieldColumn = <T extends LayoutItem>(
  field: FieldDef,
  env: LayoutEnv,
  { id = field.id, sortBy = field.value, ...column }: FieldColumnOptions<T> = {}
): AppColumnDef<T> => {
  const Renderer = fieldRenderer(field);
  const label = field.source === "builtin" ? env.t(field.label) : field.label;
  const sortable = column.sortFn !== undefined;
  return {
    id,
    accessorFn: sortBy,
    header: ({ column: tableColumn }) => {
      if (field.source === "property") {
        return <PropertyColumnHeader icon={field.icon} label={label} />;
      }
      if (!sortable) return <span className="font-medium">{label}</span>;
      // A date's header is as wide as its cells.
      return (
        <SortHeader
          column={tableColumn}
          label={label}
          className={field.kind === "date" ? "min-w-30" : undefined}
        />
      );
    },
    cell: ({ row }) => (
      <Renderer
        value={field.value(row.original)}
        item={row.original}
        field={field}
        variant="cell"
        env={env}
      />
    ),
    enableSorting: sortable,
    enableHiding: field.hideable,
    // What the Columns menu calls it, rather than its id.
    meta: { label },
    ...column,
  };
};
