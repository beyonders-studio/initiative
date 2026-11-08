import type { RowData } from "@tanstack/react-table";
import type { LucideIcon } from "lucide-react";

import type {
  PropertyDefinitionRead,
  PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";
import type { AppColumnDef } from "@/ui/lib/table";

import { PropertyValueCell } from "./PropertyValueCell";
import { iconForPropertyType } from "./propertyTypeIcons";

/**
 * Upper bound on the number of property columns appended to a table. Large
 * communities could in theory define many more; beyond this the column visibility
 * dropdown becomes unmanageable and TanStack has to keep visibility state
 * for every one. Extra definitions are silently dropped with a console
 * warning — the manager page is still the place to see them all.
 */
const PROPERTY_COLUMN_CAP = 100;

/**
 * Namespace prefix on every property column id. Prevents a user-defined
 * property named ``"status"`` / ``"priority"`` / ``"tags"`` (etc.) from
 * silently shadowing a static column with the same id in TanStack Table's
 * internal ``columnsByID`` map. Static column ids in this codebase are all
 * plain lowercase words without punctuation, so the ``:`` separator
 * guarantees no collision regardless of what property names users pick.
 */
const PROPERTY_COLUMN_ID_PREFIX = "property:";

/**
 * Column id for a property. Always prefixed with ``property:`` so it can
 * never collide with a static column id (e.g. the project-tasks table's
 * ``"status"`` / ``"priority"`` columns). The dropdown label rendering
 * reads the display name from ``columnDef.meta.label`` so end users don't
 * see the prefix — :func:`propertyColumnLabel` computes that label.
 *
 * Uses the property's name to stay stable across renders (visibility
 * state persists by id). Falls back to ``property:#<id>`` when the name is
 * empty. When two definitions in the same list share a name
 * (``isAmbiguous=true``, only possible in global views that aggregate
 * across multiple initiatives), the id + label get a ``(#<id>)`` suffix.
 */
export const propertyColumnId = (
  definition: Pick<PropertyDefinitionRead, "id" | "name">,
  isAmbiguous = false
): string => {
  const trimmed = definition.name?.trim();
  const base = trimmed && trimmed.length > 0 ? trimmed : `#${definition.id}`;
  const suffix = isAmbiguous ? ` (#${definition.id})` : "";
  return `${PROPERTY_COLUMN_ID_PREFIX}${base}${suffix}`;
};

/** Human-readable label used by the column-visibility dropdown. */
export const propertyColumnLabel = (
  definition: Pick<PropertyDefinitionRead, "id" | "name">,
  isAmbiguous = false
): string => {
  const trimmed = definition.name?.trim();
  const base = trimmed && trimmed.length > 0 ? trimmed : `#${definition.id}`;
  return isAmbiguous ? `${base} (#${definition.id})` : base;
};

/**
 * Pre-compute which definitions share a trimmed, case-insensitive name so
 * ``propertyColumnId`` can disambiguate them. Names that appear only once
 * keep the plain form; duplicates get the ``(#<id>)`` suffix.
 */
const buildAmbiguousNameSet = (definitions: PropertyDefinitionRead[]): Set<string> => {
  const counts = new Map<string, number>();
  for (const definition of definitions) {
    const trimmed = definition.name?.trim()?.toLowerCase();
    if (!trimmed) continue;
    counts.set(trimmed, (counts.get(trimmed) ?? 0) + 1);
  }
  const ambiguous = new Set<string>();
  for (const [key, value] of counts.entries()) {
    if (value > 1) ambiguous.add(key);
  }
  return ambiguous;
};

const isDefinitionAmbiguous = (
  definition: Pick<PropertyDefinitionRead, "name">,
  ambiguousNames: Set<string>
): boolean => {
  const trimmed = definition.name?.trim()?.toLowerCase();
  if (!trimmed) return false;
  return ambiguousNames.has(trimmed);
};

/**
 * Each definition with its column id and label, two that share a name told
 * apart. A board's Fields menu names properties through this too, so a
 * property reads the same in both menus.
 */
export const namePropertyColumns = (
  definitions: PropertyDefinitionRead[]
): { definition: PropertyDefinitionRead; id: string; label: string }[] => {
  const ambiguousNames = buildAmbiguousNameSet(definitions);
  return definitions.map((definition) => {
    const ambiguous = isDefinitionAmbiguous(definition, ambiguousNames);
    return {
      definition,
      id: propertyColumnId(definition, ambiguous),
      label: propertyColumnLabel(definition, ambiguous),
    };
  });
};

/** A property column's header: its type's icon and its name. */
export const PropertyColumnHeader = ({
  icon: Icon,
  label,
}: {
  icon?: LucideIcon;
  label: string;
}) => (
  <span className="inline-flex items-center gap-1.5 font-medium text-muted-foreground text-xs">
    {Icon ? <Icon className="h-3.5 w-3.5" aria-hidden /> : null}
    <span className="truncate">{label}</span>
  </span>
);

/**
 * Build a TanStack ``ColumnDef`` per property definition. Each column is
 * hidden by default (callers are expected to seed ``columnVisibility``);
 * ``enableSorting`` is off because sort across heterogeneous typed columns
 * needs server support we don't have yet.
 */
export function buildPropertyColumns<T extends RowData>(
  definitions: PropertyDefinitionRead[],
  getProperties: (row: T) => PropertySummary[] | undefined | null
): AppColumnDef<T>[] {
  if (definitions.length > PROPERTY_COLUMN_CAP) {
    console.warn(
      `[propertyColumns] capping at ${PROPERTY_COLUMN_CAP} columns (saw ${definitions.length})`
    );
  }
  const capped = definitions.slice(0, PROPERTY_COLUMN_CAP);
  const ambiguousNames = buildAmbiguousNameSet(capped);
  return capped.map((definition) => {
    const ambiguous = isDefinitionAmbiguous(definition, ambiguousNames);
    const label = propertyColumnLabel(definition, ambiguous);
    return {
      id: propertyColumnId(definition, ambiguous),
      // Read by DataTable's column-visibility dropdown so the toggle shows
      // the user-facing name (e.g. "Status") instead of the prefixed id
      // (``property:Status``).
      meta: { label },
      header: () => (
        <PropertyColumnHeader icon={iconForPropertyType(definition.type)} label={label} />
      ),
      cell: ({ row }) => {
        const rowValue = row.original as T;
        const summaries = getProperties(rowValue) ?? [];
        const summary = summaries.find((s) => s.property_id === definition.id);
        return <PropertyValueCell summary={summary} variant="cell" />;
      },
      enableHiding: true,
      enableSorting: false,
      size: 160,
    } satisfies AppColumnDef<T>;
  });
}

/**
 * Resolve the full set of column ids that ``buildPropertyColumns`` would
 * generate for the same definitions list, with duplicate names disambiguated
 * via the ``(#<id>)`` suffix. Callers use this to seed TanStack Table's
 * ``columnVisibility`` map so the default-hidden toggle keys match the
 * column ids actually rendered.
 */
export const propertyColumnIds = (definitions: PropertyDefinitionRead[]): string[] =>
  namePropertyColumns(definitions).map(({ id }) => id);
